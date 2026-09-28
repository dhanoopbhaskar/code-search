"""Model Context Protocol (MCP) server — exposes code-search via stdio transport.

Registers five tools:
  - ``search`` — hybrid keyword + semantic search.
  - ``get_symbol_definition`` — look up a symbol by FQN.
  - ``get_call_neighbors`` — traverse callers/callees.
  - ``find_related`` — find semantically similar chunks near a given line.
  - ``get_implementations`` — interface method/type → static implementers.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from src.engine.audit import AuditDatabase
from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.graph import EdgeStore
from src.engine.redactor import Redactor
from src.engine.symbols import SymbolStore

logger = logging.getLogger(__name__)


def _freshness_signal(comps: dict[str, Any]) -> dict[str, Any]:
    """Return the shared index-freshness signal, or a truthful fallback.

    Every production component set registers ``comps["freshness"]``
    (src/cli/main.py). The fallback never lies: it reports the lifecycle
    ``index_status`` from metadata with ``stale: false``.
    """
    checker = comps.get("freshness")
    if checker is not None:
        return cast(dict[str, Any], checker.signal())
    metadata = comps.get("metadata")
    status = "unindexed"
    if metadata is not None:
        try:
            status = metadata.get_index_status()
        except Exception:
            status = "unindexed"
    context_dir = comps.get("context_dir")
    index_root = str(Path(context_dir).parent) if context_dir else None
    return {
        "stale": False,
        "stale_change_count": 0,
        "modified_files": 0,
        "deleted_files": 0,
        "new_files": 0,
        "index_age_s": None,
        "index_status": status,
        "index_root": index_root,
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


def _serialize(payload: dict[str, Any], freshness: Any | None) -> str:
    """Serialize a tool payload, attaching the freshness signal when available."""
    if freshness is not None:
        payload["freshness"] = freshness.signal()
    return json.dumps(payload, default=str)


def _definition_payload(
    symbol_store: SymbolStore,
    redactor: Redactor,
    symbol: str,
    freshness: Any | None = None,
) -> str:
    """Build the ``get_symbol_definition`` result payload (the ONE shared rule).

    Derives from :meth:`SymbolStore.resolve_name` so an ambiguous name yields
    the same candidate list as every other consumer. Only an
    ``exact`` resolution is dereferenced to a full symbol + parent; ambiguous
    names report ``found: true, ambiguous: true`` with a located candidate list
    instead of a false ``found: false``.
    """
    envelope = symbol_store.resolve_name(symbol)
    if envelope["kind"] == "ambiguous":
        return _serialize(
            {
                "found": True,
                "ambiguous": True,
                "outcome": envelope.get("outcome", "ambiguous"),
                "symbol": None,
                "parent": None,
                "candidates": envelope["candidates"],
                "overloads": envelope.get("overloads", []),
            },
            freshness,
        )
    sym = envelope["symbol"]
    if sym is None:
        suggestions = [c for c in envelope["candidates"] if c.get("suggestion")]
        return _serialize(
            {
                "found": False,
                "outcome": envelope.get("outcome", "not_found"),
                "symbol": None,
                "parent": None,
                "candidates": envelope["candidates"],
                "overloads": envelope.get("overloads", []),
                "ambiguous": False,
                "suggestion": bool(suggestions),
            },
            freshness,
        )
    parent_info = None
    if sym.get("parent_symbol_id"):
        parent = symbol_store.lookup_by_fqn(sym.get("parent_fqn", "") or "")
        if parent:
            parent_info = {
                "fqn": parent["fqn"],
                "name": parent["name"],
                "kind": parent["kind"],
            }

    source_code = sym.get("source_code") or ""
    redacted_source, _redacted_count = redactor.redact(source_code)

    return _serialize(
        {
            "found": True,
            "outcome": envelope.get("outcome", "resolved"),
            "ambiguous": bool(envelope.get("ambiguous")),
            "overloads": envelope.get("overloads", []),
            "symbol": {
                "fqn": sym["fqn"],
                "conventional_fqn": sym.get("conventional_fqn"),
                "name": sym["name"],
                "kind": sym["kind"],
                "signature": sym.get("signature"),
                "file_path": sym["file_path"],
                "line_start": sym["line_start"],
                "line_end": sym["line_end"],
                "column_start": sym["column_start"],
                "column_end": sym["column_end"],
                "docstring": sym.get("docstring") or "",
                "language": sym["language"],
                "source_code": redacted_source,
            },
            "parent": parent_info,
        },
        freshness,
    )


def _call_neighbors_payload(
    symbol_store: SymbolStore,
    edge_store: EdgeStore,
    symbol: str,
    direction: str = "both",
    max_depth: int = 1,
    freshness: Any | None = None,
    transitive: bool = False,
) -> str:
    """Build the ``get_call_neighbors`` result payload (the ONE shared rule).

    Derives from :meth:`SymbolStore.resolve_name` so an ambiguous name yields
    the same candidate list as every other consumer. Only an
    ``exact`` resolution is dereferenced to a symbol id and traversed;
    ambiguous / suggestion / not-found names return an empty graph with the
    candidate list attached instead of crashing.

    Traversal is direct-only unless *transitive* is set; when set it expands to
    *max_depth* (which each surface clips to the configured graph depth before
    calling here). A transitive request bounded to depth 1 degrades to
    direct-only without error.

    ``direction == "implements"`` is the additive implementation-lookup entry
    point: it delegates to the shared :func:`find_implementations` rule and
    returns the identical ``implementations`` content with empty
    ``callers``/``callees``. Any other direction is byte-identical to before.
    """
    if direction == "implements":
        from src.engine.implementations import find_implementations

        result = find_implementations(symbol_store, edge_store, symbol)
        result["callers"] = []
        result["callees"] = []
        return _serialize(result, freshness)

    envelope = symbol_store.resolve_name(symbol)
    if envelope["kind"] == "ambiguous":
        return _serialize(
            {
                "ambiguous": True,
                "outcome": envelope.get("outcome", "ambiguous"),
                "symbol": None,
                "candidates": envelope["candidates"],
                "callers": [],
                "callees": [],
            },
            freshness,
        )
    sym = envelope["symbol"]
    if sym is None:
        return _serialize(
            {
                "symbol": None,
                "outcome": envelope.get("outcome", "not_found"),
                "callers": [],
                "callees": [],
            },
            freshness,
        )
    effective_depth = max_depth if transitive else 1
    graph_result = edge_store.get_call_graph(sym["id"], direction, effective_depth)
    callers = graph_result.get("callers", [])
    callees = graph_result.get("callees", [])
    return _serialize(
        {
            "outcome": envelope.get("outcome", "resolved"),
            "symbol": {
                "fqn": sym["fqn"],
                "kind": sym["kind"],
                "file_path": sym["file_path"],
                "line_start": sym["line_start"],
                "signature": sym.get("signature"),
            },
            "callers": callers,
            "callees": callees,
        },
        freshness,
    )


def _implementations_payload(
    symbol_store: SymbolStore,
    edge_store: EdgeStore,
    symbol: str,
    freshness: Any | None = None,
    max_depth: int | None = None,
) -> str:
    """Build the ``get_implementations`` result payload (the ONE shared rule).

    Delegates to :func:`src.engine.implementations.find_implementations` so the
    dedicated tool and the ``implements`` traversal direction return identical
    outcome, implementations, and order. Only transport concerns (freshness)
    are added here.
    """
    from src.engine.implementations import find_implementations

    result = find_implementations(symbol_store, edge_store, symbol, max_depth=max_depth)
    return _serialize(result, freshness)


def _find_related_payload(
    comps: dict[str, Any],
    file_path: str,
    line_number: int,
    limit: int,
) -> str:
    """Build the ``find_related`` result payload (the ONE shared rule).

    Resolves *file_path* to its stored indexed spelling, locates the chunk
    containing *line_number*, embeds its content, and returns the nearest
    neighbours from the vector index. The anchor chunk itself is excluded
    (self-match), and a failed embed reports a clear
    ``vector_health: false`` status instead of a bare empty array.

    By default the anchor chunk's own **file** is excluded from the neighbour
    set; when that exclusion leaves no cross-file neighbour the
    response is explicitly labelled ``same_file_only`` or ``empty`` rather than
    silently presenting same-file self-chunks as cross-file relatedness. The
    candidate search fetches ``limit + 1`` entries before filtering so an
    anchor that is its own cosine top-1 still yields a full ``limit`` of
    neighbours (the limit-1 defect).

    Args:
        comps: The shared component registry.
        file_path: Absolute or project-relative path to a file.
        line_number: Line within the file to anchor the chunk.
        limit: Maximum related chunks to return; capped at the configured
            ``find_related_limit``.

    Returns:
        A JSON payload with ``results`` (anchor excluded), ``vector_health``,
        ``status`` (``cross_file``/``same_file_only``/``empty``),
        ``query_time_ms``, and ``freshness`` — or an ``error`` payload when no
        indexed chunk is found.
    """
    start = time.monotonic()
    from pathlib import Path

    from src.engine.paths import normalize_indexed_path, resolve_stored_path
    from src.engine.semantic_signals import rerank_with_semantic

    embedding_gen: EmbeddingGenerator = comps["embedding_gen"]
    vector_index: VectorIndex = comps["vector_index"]
    settings = comps.get("settings") or Settings.from_env()
    redactor = comps.get("redactor") or Redactor()

    def _payload(payload: dict[str, Any]) -> str:
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        return _serialize(payload, comps.get("freshness"))

    index_root = Path(comps["context_dir"]).parent
    stored_root = comps["metadata"].get("index_root")
    if stored_root:
        index_root = Path(stored_root)

    stored_path: str | None = None
    normalized = normalize_indexed_path(file_path, index_root)
    if normalized is not None:
        with comps["db"].connect() as conn:
            stored_path = resolve_stored_path(normalized, conn)

    if stored_path is None:
        return _payload({"error": f"No indexed chunk found at '{file_path}:{line_number}'"})

    with comps["db"].connect() as conn:
        # Anchor the most specific (smallest) chunk containing the line so a
        # method-body anchor embeds the method rather than the enclosing class
        # chunk — otherwise semantic signals (type sharing, call proximity)
        # degrade to package-only.
        row = conn.execute(
            "SELECT id, fqn, content, language FROM code_chunks "
            "WHERE file_path = ? AND line_start <= ? AND line_end >= ? "
            "ORDER BY (line_end - line_start) ASC, line_start ASC "
            "LIMIT 1;",
            (stored_path, line_number, line_number),
        ).fetchone()
        if row is None:
            return _payload({"error": f"No indexed chunk found at '{file_path}:{line_number}'"})
        anchor_id = row["id"]
        chunk_content = row["content"] or ""

    query_vec = embedding_gen.encode(chunk_content)
    if query_vec is None:
        return _payload(
            {
                "results": [],
                "vector_health": False,
                "status": "empty",
                "explanation": (
                    "vector layer unavailable; find_related requires the embedding model"
                ),
            }
        )

    limit = min(limit, settings.find_related_limit)
    if vector_index.size <= 1:
        explanation = (
            "no related chunks found; the index holds only the anchor chunk"
            if vector_index.size == 1
            else "no related chunks found; the vector index is empty"
        )
        return _payload(
            {
                "results": [],
                "vector_health": vector_index.size == 1,
                "status": "empty",
                "explanation": explanation,
            }
        )

    exclude_file = bool(settings.find_related_exclude_file)
    # Directional boilerplate suppression — a non-boilerplate
    # anchor excludes boilerplate-shape neighbors (MODEL/DTO/ASSEMBLER/
    # EXCEPTION) by default; a genuine DTO/model anchor still finds its
    # scaffolding peers when the anchor is itself boilerplate. Setting
    # ``CODE_SEARCH_FIND_RELATED_EXCLUDE_BOILERPLATE=false`` switches the
    # exclusion to a down-weight.
    from src.engine.classification import FileRole, file_role

    boilerplate_roles = {
        FileRole.MODEL,
        FileRole.DTO,
        FileRole.ASSEMBLER,
        FileRole.EXCEPTION,
    }
    analysis_paths = set(settings.analysis_artifact_paths)
    anchor_role = file_role(stored_path, analysis_paths=analysis_paths)
    anchor_is_boilerplate = anchor_role in boilerplate_roles
    boilerplate_on = bool(settings.find_related_exclude_boilerplate)
    exclude_boilerplate = boilerplate_on and not anchor_is_boilerplate
    downweight_boilerplate = (not boilerplate_on) and not anchor_is_boilerplate

    # Fetch candidates before filtering (the limit-1 fix): an anchor that is
    # its own cosine top-1 must still yield a full limit of neighbours. When
    # semantic reranking is enabled, a wider pool (limit + 50)
    # is fetched so functionally-related neighbours sitting just outside the
    # pure-vector top-(limit+1) can still be promoted by their semantic signals.
    candidate_k = limit + 1
    if settings.find_related_semantic_blend > 0:
        candidate_k = max(candidate_k, limit + 50)
    search_results = vector_index.search(
        query_vec,
        top_k=candidate_k,
        exclude_file_paths={stored_path} if exclude_file else None,
    )

    # --- Semantic reranking ---
    # Fetch anchor symbol_id from code_chunks -> symbols join
    anchor_symbol_id = None
    anchor_fqn = None
    anchor_kind = None
    with comps["db"].connect() as conn:
        row = conn.execute(
            "SELECT s.id, s.fqn, s.kind FROM code_chunks c "
            "JOIN symbols s ON c.fqn = s.fqn "
            "WHERE c.id = ? LIMIT 1;",
            (anchor_id,),
        ).fetchone()
        if row:
            anchor_symbol_id = row["id"]
            anchor_fqn = row["fqn"]
            anchor_kind = row["kind"]

    # Only apply semantic reranking if enabled (semantic_blend > 0) and anchor has symbol
    semantic_reranked = None
    if settings.find_related_semantic_blend > 0 and anchor_symbol_id:
        # Prepare anchor info for semantic reranking
        anchor_info = {
            "chunk_id": anchor_id,
            "fqn": anchor_fqn,
            "file_path": stored_path,
            "symbol_id": anchor_symbol_id,
            "kind": anchor_kind,
        }
        semantic_reranked = rerank_with_semantic(
            search_results,
            anchor_info,
            comps["db"],
            settings,
            limit + 1,  # Fetch more candidates for reranking
        )
        # Convert reranked results back to (chunk_id, final_score) tuples
        # for consumption by _build_results
        search_results = [(r["chunk_id"], r["final_score"]) for r in semantic_reranked]

    def _build_results(
        scored: list[tuple[int, float]], same_file_flag: bool
    ) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
        """Return ``(kept_results, boilerplate_only, raw_results)``.

        Applies the directional boilerplate exclusion/down-weight; ``kept`` is
        the neighbour set after the filter, ``raw`` is the unfiltered set
        (used for the ``best_effort`` label), and ``boilerplate_only``
        reports whether the only similar content was boilerplate-shape.
        """
        chunk_ids = [cid for cid, _ in scored if cid != anchor_id]
        if not chunk_ids:
            return [], False, []
        score_map = {cid: sc for cid, sc in scored}
        placeholders = ",".join("?" for _ in chunk_ids)
        with comps["db"].connect() as conn:
            chunk_rows = conn.execute(
                f"SELECT id, fqn, file_path, line_start, line_end, content, "
                f"language FROM code_chunks "
                f"WHERE id IN ({placeholders});",
                chunk_ids,
            ).fetchall()

        rows: list[dict[str, Any]] = []
        had_boilerplate = False
        for cr in chunk_rows:
            role = file_role(cr["file_path"], analysis_paths=analysis_paths)
            if role in boilerplate_roles:
                had_boilerplate = True
            content = cr["content"] or ""
            redacted_content, _redacted_count = redactor.redact(content)
            rows.append(
                {
                    "chunk_id": cr["id"],
                    "file_path": cr["file_path"],
                    "line_start": cr["line_start"],
                    "line_end": cr["line_end"],
                    "content": redacted_content,
                    "fqn": cr["fqn"],
                    "language": cr["language"],
                    "similarity": score_map.get(cr["id"], 0.0),
                    "same_file": same_file_flag,
                    "file_role": role,
                }
            )
        # Rank the neighbours by their score first so every branch below
        # (exclusion, down-weighting, all-boilerplate) returns score-ordered
        # results. Without this the exclude-boilerplate path emitted rows in
        # arbitrary DB fetch order while ``similarity`` carried the true score.
        rows.sort(key=lambda r: r["similarity"], reverse=True)
        if downweight_boilerplate:
            penalty = settings.find_related_same_file_penalty
            for r in rows:
                if r["file_role"] in boilerplate_roles:
                    r["similarity"] = r["similarity"] * penalty
            rows.sort(key=lambda r: r["similarity"], reverse=True)
        if exclude_boilerplate:
            kept = [r for r in rows if r["file_role"] not in boilerplate_roles]
            boilerplate_only = (not kept) and had_boilerplate
            return kept[:limit], boilerplate_only, rows[:limit]
        all_boilerplate = bool(rows) and all(r["file_role"] in boilerplate_roles for r in rows)
        return rows[:limit], all_boilerplate, rows[:limit]

    def _best_effort(rows: list[dict[str, Any]], same_file: bool) -> str:
        return _payload(
            {
                "results": rows,
                "vector_health": True,
                "status": "best_effort",
                "explanation": (
                    "only boilerplate-shape content is similar to this anchor; "
                    "returning the best-effort match"
                ),
                "same_file": same_file,
            }
        )

    if exclude_file:
        cross_results, cross_boilerplate_only, cross_raw = _build_results(
            search_results, same_file_flag=False
        )
        if cross_results:
            return _payload(
                {"results": cross_results, "vector_health": True, "status": "cross_file"}
            )
        if cross_boilerplate_only:
            return _best_effort(cross_raw, same_file=False)
        # Exclusion left no cross-file neighbour: search the full index again
        # (anchor file included) for the best-effort same-file result.
        fallback = vector_index.search(query_vec, top_k=limit + 1)
        same_file_results, same_boilerplate_only, _same_file_raw = _build_results(
            fallback, same_file_flag=True
        )
        if same_file_results:
            if same_boilerplate_only:
                return _best_effort(same_file_results, same_file=True)
            return _payload(
                {
                    "results": same_file_results,
                    "vector_health": True,
                    "status": "same_file_only",
                    "explanation": (
                        "no cross-file neighbours; returning the best same-file result"
                    ),
                }
            )
        return _payload(
            {
                "results": [],
                "vector_health": True,
                "status": "empty",
                "explanation": (
                    "no related chunks found; the anchor file holds the only similar content"
                ),
            }
        )

    # Down-weighting mode (CODE_SEARCH_FIND_RELATED_EXCLUDE_FILE=false): the
    # anchor file is kept, but same-file chunks are down-weighted so cross-file
    # neighbours always outrank them. Cross-file candidates are
    # ranked first by score, then same-file candidates by their penalized score.
    penalty = settings.find_related_same_file_penalty
    chunk_ids = [cid for cid, _ in search_results]
    placeholders = ",".join("?" for _ in chunk_ids)
    with comps["db"].connect() as conn:
        file_rows = conn.execute(
            f"SELECT id, file_path FROM code_chunks WHERE id IN ({placeholders});",
            chunk_ids,
        ).fetchall()
    file_by_id = {r["id"]: r["file_path"] for r in file_rows}
    anchor_file = stored_path
    cross_scored: list[tuple[int, float]] = []
    same_scored: list[tuple[int, float]] = []
    for cid, score in search_results:
        if cid == anchor_id:
            continue
        if file_by_id.get(cid, "") == anchor_file:
            same_scored.append((cid, score * penalty))
        else:
            cross_scored.append((cid, score))
    cross_scored.sort(key=lambda item: item[1], reverse=True)
    same_scored.sort(key=lambda item: item[1], reverse=True)
    scored = (cross_scored + same_scored)[:limit]

    cross_results, cross_boilerplate_only, _cross_raw = _build_results(
        cross_scored[:limit], same_file_flag=False
    )
    if cross_results:
        return _payload({"results": cross_results, "vector_health": True, "status": "cross_file"})
    same_file_results, same_boilerplate_only, _same_file_raw = _build_results(
        scored, same_file_flag=True
    )
    if same_file_results:
        if same_boilerplate_only or cross_boilerplate_only:
            return _best_effort(same_file_results, same_file=True)
        return _payload(
            {
                "results": same_file_results,
                "vector_health": True,
                "status": "same_file_only",
                "explanation": "no cross-file neighbours; returning the best same-file result",
            }
        )
    return _payload(
        {
            "results": [],
            "vector_health": True,
            "status": "empty",
            "explanation": "no related chunks found",
        }
    )


class MCPServer:
    """Serves the code-search engine to MCP clients over stdio.

    Wraps a component registry (see ``_initialize_components``) and registers
    the five MCP tools: ``search``, ``get_symbol_definition``,
    ``get_call_neighbors``, ``get_implementations``, and ``find_related``.
    """

    def __init__(self, components: dict[str, Any]) -> None:
        """Create an MCP server wired to the shared component registry.

        Args:
            components: The component registry from
                ``_initialize_components``; ``settings`` is read eagerly and
                the rest lazily at run time.
        """
        self._components = components
        self._tools: dict[str, object] = {}
        self._settings: Settings = components.get("settings", Settings.from_env())

    def register_tool(self, name: str, handler: object) -> None:
        """Register a tool *handler* under *name*.

        Kept for API symmetry; the current implementation registers tools via
        ``@mcp.tool()`` decorators in :meth:`run` instead.

        Args:
            name: The tool name clients invoke.
            handler: The callable handling the tool.
        """
        self._tools[name] = handler

    def build_fastmcp(self) -> Any:
        """Build the FastMCP server with the four MCP tools registered.

        Registers ``search``, ``get_symbol_definition``, ``get_call_neighbors``,
        and ``find_related`` so a test or embedder can exercise the real tool
        bodies without starting the stdio loop.

        Returns:
            A ready-to-serve ``fastmcp.FastMCP`` instance.

        Raises:
            ImportError: When ``fastmcp`` is not installed.
        """
        try:
            import fastmcp
            from fastmcp import FastMCP

            fastmcp.settings.check_for_updates = "off"
            mcp = FastMCP("code-search")

            comps = self._components
            audit_db: AuditDatabase = comps["audit_db"]
            redactor: Redactor = comps["redactor"]
            settings = self._settings
            from src.engine.metrics import MetricsCollector

            mc: MetricsCollector | None = comps.get("metrics_collector")

            @mcp.tool()
            async def search(
                query: str,
                limit: int = 10,
                language: str | None = None,
                include_test_files: bool = True,
                mode: str = "ranked",
                content: str | None = None,
                no_model: bool = False,
                matching: str = "all_tokens",
            ) -> str:
                """Run hybrid search, returning redacted, reranked JSON results.

                Args:
                    query: The natural-language search query.
                    limit: Requested result count; capped at the configured
                        ``max_results`` (a ``result_limit_capped`` flag is set
                        on each result when truncated).
                    language: Optional language filter.
                    include_test_files: Whether to include test files.
                    mode: Search mode — ``ranked`` (default), ``exhaustive``
                        (complete line-wise match set), or ``enumerate``
                        (named symbol-kind list).
                    content: Content-type scope — ``code``, ``config``,
                        ``docs``, ``all``, or ``code_focused``. Omitting it
                        (``None``) means no scope preference: the effective
                        default is code-focused (code + config), and a
                        documentation-shaped query whose default search finds
                        nothing is automatically searched with ``all``. Use
                        ``content="all"`` to force documentation inclusion.
                    no_model: Fast path that skips the vector model (lexical
                        fusion only).
                    matching: Exhaustive matching semantics — ``literal``,
                        ``all_tokens`` (default), or ``any_token``; ignored
                        outside exhaustive mode.

                Returns:
                    A JSON object with ``results`` and ``freshness``.
                """
                start = time.monotonic()
                from src.engine.search import (
                    DEFAULT_CONTENT_SCOPE,
                    HybridSearch,
                    query_symbol_identifier,
                )

                if no_model:
                    hs: HybridSearch = HybridSearch(
                        comps["db"],
                        comps["vector_index"],
                        comps["embedding_gen"],
                        comps.get("settings") or settings,
                        no_model=True,
                    )
                else:
                    hs = comps["search"]
                original_limit = limit
                limit = min(limit, settings.max_results)
                result_limit_capped = limit < original_limit
                envelope = hs.search(
                    query,
                    limit=limit,
                    language=language,
                    include_tests=include_test_files,
                    mode=mode,
                    content=content,
                    matching=matching,
                )
                raw = envelope["results"]
                env_mode = str(envelope.get("mode", "ranked"))
                if env_mode in ("exhaustive", "enumerate"):
                    count_field = "total_count"
                    total = int(envelope.get("total_count", len(raw)))
                else:
                    count_field = "total_matches"
                    total = int(envelope["total_matches"])
                truncated = bool(envelope["truncated"])
                identifier = query_symbol_identifier(query)
                query_terms = [identifier] if identifier else None
                reranked = comps["reranker"].rerank(raw, query_terms=query_terms, query=query)

                redacted = redactor.redact_results(reranked)
                total_redacted = sum(r.get("redacted_count", 0) for r in redacted)

                for r in redacted:
                    r["result_limit_capped"] = result_limit_capped

                engine_duration = envelope.get("query_time_ms")
                duration_ms = (
                    round(engine_duration)
                    if engine_duration is not None
                    else int((time.monotonic() - start) * 1000)
                )
                audit_db.write_entry(
                    query_type="search",
                    query_summary=query[: settings.query_summary_length],
                    result_count=len(redacted),
                    duration_ms=duration_ms,
                    redacted_count=total_redacted,
                )

                if mc:
                    mc.record_query(duration_ms)
                    if total_redacted > 0:
                        mc.record_redaction(total_redacted)

                response: dict[str, Any] = {
                    "results": redacted,
                    count_field: total,
                    "truncated": truncated,
                    "vector_health": bool(envelope.get("vector_health")),
                    "mode": env_mode,
                    "confidence": envelope.get("confidence", "none"),
                    "explanation": envelope.get("explanation"),
                    "freshness": _freshness_signal(comps),
                }
                if envelope.get("content") is not None:
                    response["content"] = envelope["content"]
                if envelope.get("scope") is not None:
                    response["scope"] = envelope["scope"]
                if envelope.get("matching_semantics") is not None:
                    response["matching_semantics"] = envelope["matching_semantics"]
                response["query_time_ms"] = round(duration_ms, 1)
                if envelope.get("model_status") is not None:
                    response["model_status"] = envelope["model_status"]
                if envelope.get("ranked_path") is not None:
                    response["ranked_path"] = envelope["ranked_path"]
                if envelope.get("warmup_state") is not None:
                    response["warmup_state"] = envelope["warmup_state"]
                if "degraded_reason" in envelope:
                    response["degraded_reason"] = envelope["degraded_reason"]
                if envelope.get("no_match") is not None:
                    response["no_match"] = envelope["no_match"]
                if "complete" in envelope:
                    response["complete"] = bool(envelope["complete"])
                if envelope.get("excluded"):
                    response["excluded"] = envelope["excluded"]
                if envelope.get("best_effort"):
                    response["best_effort"] = True

                # Surface per-line occurrence metadata in exhaustive responses
                if env_mode == "exhaustive":
                    if envelope.get("occurrence_count") is not None:
                        response["occurrence_count"] = envelope["occurrence_count"]
                    if envelope.get("literal") is not None:
                        response["literal"] = envelope["literal"]
                    if envelope.get("occurrences_per_line") is not None:
                        response["occurrences_per_line"] = envelope["occurrences_per_line"]
                    if envelope.get("occurrence_line_numbers") is not None:
                        response["occurrence_line_numbers"] = envelope["occurrence_line_numbers"]

                # Serving-path transparency: detect a rebuilt index and
                # surface the visible "index changed — restart required"
                # envelope (or the code-scope config hint) instead of a
                # silent empty/stale result.
                from src.engine.index_service import IndexChangeDetector
                from src.engine.response_service import build_response

                detector = comps.get("index_change_detector")
                if detector is None:
                    detector = IndexChangeDetector.from_metadata_store(comps["metadata"])
                    comps["index_change_detector"] = detector
                serving = build_response(
                    redacted,
                    query,
                    detector,
                    content_scope=envelope.get("content") or DEFAULT_CONTENT_SCOPE,
                    metadata_store=comps["metadata"],
                    scope_signal=(envelope.get("scope") or {}).get("signal"),
                )

                # If index changed and reload is required, perform in-process reload
                if serving.get("reload_required"):
                    logger.info("Index change detected, performing full in-process reload")
                    # Reset embedding generator to force model reload
                    embedding_gen: EmbeddingGenerator = comps["embedding_gen"]
                    embedding_gen.reset_model()
                    # Reload vector index from disk
                    vector_index: VectorIndex = comps["vector_index"]
                    vector_index.load()
                    # Reset search engine caches (symbol store, vocabularies, BM25 corpus)
                    search_engine: HybridSearch = comps["search"]
                    search_engine.reset_caches()
                    # Re-initialize the embedding model for the search engine
                    search_engine._embedding_generator = embedding_gen
                    # Mark reload as complete in detector and update metadata store
                    detector.mark_reload_complete(comps["metadata"])
                    # Update serving envelope to reflect reload
                    serving = build_response(
                        redacted,
                        query,
                        detector,
                        content_scope=envelope.get("content") or DEFAULT_CONTENT_SCOPE,
                        metadata_store=comps["metadata"],
                        scope_signal=(envelope.get("scope") or {}).get("signal"),
                    )
                if serving.get("envelope") is not None:
                    scope = envelope.get("scope") or {}
                    engine_signal = scope.get("signal")
                    scope_override = scope.get("override")
                    envelope_text = serving["envelope"]
                    if (
                        engine_signal is not None
                        and envelope_text == engine_signal
                        and scope_override
                        and scope_override != scope.get("effective")
                    ):
                        # Render the neutral override token in the MCP dialect so
                        # no MCP caller is shown a CLI-only flag. Suppressed when
                        # the override equals the effective scope, as on an
                        # inferred documentation result: the effective ``all``
                        # scope already includes documentation, so repeating the
                        # override would contradict the response's own signal.
                        envelope_text = (
                            f'{envelope_text} (override with content="{scope_override}")'
                        )
                    response["envelope"] = envelope_text
                response["index_status"] = serving["index_status"]
                response["index_changed"] = bool(serving.get("index_changed"))
                response["reload_required"] = bool(serving.get("reload_required"))
                return json.dumps(response, default=str)

            @mcp.tool()
            async def get_symbol_definition(symbol: str) -> str:
                """Return a symbol's definition via the shared resolution rule.

                Args:
                    symbol: The symbol FQN to look up.

                Returns:
                    A JSON payload describing the symbol, its parent, and
                    ambiguous/not-found candidates when applicable.
                """
                start = time.monotonic()
                payload = _definition_payload(
                    comps["symbol_store"], redactor, symbol, comps.get("freshness")
                )
                data = json.loads(payload)
                symbol_payload = data.get("symbol") or {}
                source_code = (
                    symbol_payload.get("source_code") if isinstance(symbol_payload, dict) else ""
                ) or ""
                redacted_count = source_code.count("[REDACTED]")

                duration_ms = int((time.monotonic() - start) * 1000)
                audit_db.write_entry(
                    query_type="get_symbol_definition",
                    query_summary=symbol[: settings.query_summary_length],
                    result_count=1 if data.get("symbol") else 0,
                    duration_ms=duration_ms,
                    redacted_count=redacted_count,
                )

                if mc:
                    mc.record_query(duration_ms)
                    if redacted_count > 0:
                        mc.record_redaction(redacted_count)

                data["query_time_ms"] = duration_ms
                return json.dumps(data, default=str)

            @mcp.tool()
            async def get_call_neighbors(
                symbol: str,
                direction: str = "both",
                max_depth: int = 1,
                transitive: bool = False,
            ) -> str:
                """Return a symbol's callers and/or callees as a JSON payload.

                Args:
                    symbol: The symbol FQN to traverse.
                    direction: ``both``, ``callers``, or ``callees``.
                    max_depth: Maximum traversal depth; capped at the
                        configured graph depth.
                    transitive: Expand to ``max_depth`` when true; direct-only
                        (depth 1) when false.

                Returns:
                    A JSON payload with the root ``symbol`` plus ``callers``
                    and ``callees``.
                """
                start = time.monotonic()
                edge_store = comps.get("edge_store")
                if not isinstance(edge_store, EdgeStore):
                    edge_store = EdgeStore(comps["db"])
                depth = min(max_depth, settings.max_graph_depth)
                payload = _call_neighbors_payload(
                    comps["symbol_store"],
                    edge_store,
                    symbol,
                    direction,
                    depth,
                    comps.get("freshness"),
                    transitive,
                )
                data = json.loads(payload)
                callers = data.get("callers") or []
                callees = data.get("callees") or []

                total_results = len(callers) + len(callees)
                duration_ms = int((time.monotonic() - start) * 1000)
                audit_db.write_entry(
                    query_type="get_call_neighbors",
                    query_summary=symbol[: settings.query_summary_length],
                    result_count=total_results,
                    duration_ms=duration_ms,
                    redacted_count=0,
                )

                if mc:
                    mc.record_query(duration_ms)

                data["query_time_ms"] = duration_ms
                return json.dumps(data, default=str)

            @mcp.tool()
            async def get_implementations(symbol: str) -> str:
                """Return the static implementations of an interface member or type.

                Args:
                    symbol: An interface method (or type) reference in any
                        resolution form (FQN, conventional FQN, partial, or
                        bare name).

                Returns:
                    A JSON payload with ``outcome`` (``resolved`` |
                    ``ambiguous`` | ``not_found`` | ``no_static_implementation``),
                    the resolved ``symbol`` and ``declaring_type``, an ordered
                    ``implementations`` list, ``candidates`` when ambiguous, and
                    an ``explanation`` for a no-static outcome.
                """
                start = time.monotonic()
                edge_store = comps.get("edge_store")
                if not isinstance(edge_store, EdgeStore):
                    edge_store = EdgeStore(comps["db"])
                payload = _implementations_payload(
                    comps["symbol_store"],
                    edge_store,
                    symbol,
                    comps.get("freshness"),
                )
                data = json.loads(payload)
                implementations = data.get("implementations") or []
                duration_ms = int((time.monotonic() - start) * 1000)
                audit_db.write_entry(
                    query_type="get_implementations",
                    query_summary=symbol[: settings.query_summary_length],
                    result_count=len(implementations),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                data["query_time_ms"] = duration_ms
                return json.dumps(data, default=str)

            @mcp.tool()
            async def find_related(
                file_path: str,
                line_number: int,
                limit: int = 5,
            ) -> str:
                """Find chunks semantically related to the code at a location.

                Resolves the caller-supplied *file_path* to its stored indexed
                spelling, locates the chunk containing *line_number*, embeds
                it, and returns the nearest neighbours from the vector index.

                Args:
                    file_path: Absolute or project-relative path to a file.
                    line_number: Line within the file to anchor the chunk.
                    limit: Maximum related chunks to return; capped at the
                        configured ``find_related_limit``.

                Returns:
                    A JSON payload with ``results`` (or an ``error`` when no
                    indexed chunk is found) and ``freshness``.
                """
                start = time.monotonic()
                payload = _find_related_payload(comps, file_path, line_number, limit)
                data = json.loads(payload)
                results = data.get("results") or []
                total_redacted = sum(r.get("redacted_count", 0) for r in results)
                duration_ms = int((time.monotonic() - start) * 1000)
                audit_db.write_entry(
                    query_type="find_related",
                    query_summary=f"{file_path}:{line_number}",
                    result_count=len(results),
                    duration_ms=duration_ms,
                    redacted_count=total_redacted,
                )
                if mc:
                    mc.record_query(duration_ms)
                    if total_redacted > 0:
                        mc.record_redaction(total_redacted)
                return payload

            return mcp
        except ImportError:
            logger.error("fastmcp not installed. MCP server unavailable.")
            raise

    def run(self, transport: str = "stdio") -> None:
        """Serve the MCP tools over the requested transport.

        Only ``stdio`` is supported. Builds the FastMCP server via
        :meth:`build_fastmcp` and blocks serving inside an air-gap enforcement
        context.

        Args:
            transport: The MCP transport name; anything other than ``stdio``
                raises ``ValueError``.

        Raises:
            ValueError: When *transport* is not ``stdio``.
            ImportError: When ``fastmcp`` is not installed.
        """
        if transport != "stdio":
            raise ValueError(f"Unsupported transport: {transport}")
        from src.engine.redactor import air_gap_enforcement

        with air_gap_enforcement():
            self.build_fastmcp().run(transport="stdio")


def create_server(components: dict[str, Any]) -> MCPServer:
    """Create an :class:`MCPServer` around the given component registry.

    Args:
        components: The component registry from ``_initialize_components``.

    Returns:
        A configured :class:`MCPServer` ready to serve.
    """

    return MCPServer(components)
