"""Model Context Protocol (MCP) server — exposes code-search via stdio transport.

Registers these tools:
  - ``search`` — hybrid keyword + semantic search.
  - ``get_symbol_definition`` — look up a symbol by FQN.
  - ``get_call_neighbors`` — traverse callers/callees.
  - ``find_related`` — find semantically similar chunks near a given line.
  - ``get_implementations`` — interface method/type → static implementers.
  - ``query_graph`` — answer a multi-hop question by graph traversal.
  - ``shortest_path`` — shortest path between two symbols.
  - ``explain_symbol`` — symbol metadata, relations, rationale, and doc links.
  - ``get_impact`` — symbols impacted by changed files.
  - ``get_graph_schema`` — labels, edge types, tiers, coverage, generation.
  - ``get_file_outline`` — declarations of one file in source order.
  - ``search_symbols`` — structural search by regex, kind, file, and degree.
  - ``find_dead_code`` — callables with no proven production reference.
  - ``get_architecture`` — bounded architecture aspects.
  - ``check_index_coverage`` — distinguish "not found" from "not indexed".
  - ``detect_changes`` — git/explicit changes → files, impact, or tests.
  - ``cypher_query`` — read-only Cypher subset for multi-hop/aggregate questions.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from code_search.engine.audit import AuditDatabase
from code_search.engine.config import Settings
from code_search.engine.embeddings import EmbeddingGenerator, VectorIndex
from code_search.engine.graph import EdgeStore
from code_search.engine.redactor import Redactor
from code_search.engine.symbols import SymbolStore

logger = logging.getLogger(__name__)


def _freshness_signal(comps: dict[str, Any]) -> dict[str, Any]:
    """Return the shared index-freshness signal, or a truthful fallback.

    Every production component set registers ``comps["freshness"]``
    (code_search/cli/main.py). The fallback never lies: it reports the lifecycle
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
    db: Any | None = None,
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
        from code_search.engine.implementations import find_implementations

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
    coverage: dict[str, Any] | None = None
    if db is not None:
        from code_search.engine.graph_query import edge_resolution_stats

        coverage = edge_resolution_stats(db)
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
            **({"coverage": coverage} if coverage is not None else {}),
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

    Delegates to :func:`code_search.engine.implementations.find_implementations` so the
    dedicated tool and the ``implements`` traversal direction return identical
    outcome, implementations, and order. Only transport concerns (freshness)
    are added here.
    """
    from code_search.engine.implementations import find_implementations

    result = find_implementations(symbol_store, edge_store, symbol, max_depth=max_depth)
    return _serialize(result, freshness)


def _find_related_payload(
    comps: dict[str, Any],
    file_path: str,
    line_number: int,
    limit: int,
) -> str:
    """Build the ``find_related`` result payload (the ONE shared rule).

    Delegates to :func:`code_search.engine.find_related.find_related` so the
    MCP tool, the in-process CLI, and the daemon-forwarded CLI resolve the
    anchor chunk and rank neighbours identically. Only transport concerns
    (freshness) are added here.
    """
    from code_search.engine.find_related import find_related

    payload = find_related(comps, file_path, line_number, limit)
    return _serialize(payload, comps.get("freshness"))


class MCPServer:
    """Serves the code-search engine to MCP clients over stdio.

    Wraps a component registry (see ``_initialize_components``) and registers
    the MCP tools: ``search``, ``get_symbol_definition``,
    ``get_call_neighbors``, ``get_implementations``, ``find_related``,
    ``query_graph``, ``shortest_path``, ``explain_symbol``, ``get_impact``,
    ``get_graph_schema``, ``get_file_outline``, ``search_symbols``,
    ``get_architecture``, ``check_index_coverage``, ``detect_changes``, and
    ``cypher_query``.
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
        """Build the FastMCP server with every MCP tool registered.

        Registers the search, definition, call-neighbour, implementation,
        related-search, graph-query, path, explain, impact, schema, outline,
        structural-search, architecture, coverage, and change-detection tools
        so a test or embedder can exercise the real tool bodies without
        starting the stdio loop.

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
            from code_search.engine.metrics import MetricsCollector

            mc: MetricsCollector | None = comps.get("metrics_collector")

            @mcp.tool()
            async def search(
                query: str,
                limit: int = 10,
                language: str | None = None,
                include_test_files: bool = False,
                mode: str = "ranked",
                content: str | None = None,
                no_model: bool = False,
                matching: str = "all_tokens",
                regex: bool = False,
                compact: bool = True,
                max_snippet_lines: int | None = None,
                paths_only: bool = False,
                allow_weak: bool = False,
            ) -> str:
                """Run hybrid search, returning redacted, reranked JSON results.

                Args:
                    query: The natural-language search query.
                    limit: Requested result count; capped at the configured
                        ``max_results`` (a ``result_limit_capped`` flag is set
                        on each result when truncated).
                    language: Optional language filter.
                    include_test_files: Whether to include test files;
                        excluded by default (demoted, not indexed-out).
                    mode: Search mode — ``ranked`` (default), ``exhaustive``
                        (complete line-wise match set), or ``enumerate``
                        (named symbol-kind list).
                    content: Content-type scope — ``code``, ``config``,
                        ``docs``, ``all``, or ``code_focused``. Omitting it
                        (``None``) means no scope preference: a code-shaped
                        query defaults to ``code``, a documentation-shaped
                        query is widened to ``all``, and other queries use
                        code-focused (code + config). Use ``content="all"``
                        to force documentation inclusion.
                    no_model: Fast path that skips the vector model (lexical
                        fusion only).
                    matching: Exhaustive matching semantics — ``literal``,
                        ``all_tokens`` (default), or ``any_token``; ignored
                        outside exhaustive mode.
                    regex: Exhaustive-only regular-expression mode; the query
                        is compiled as a Python regex instead of tokenized.
                    compact: Return the agent-sized result envelope (default).
                    max_snippet_lines: Content lines per result; ``0`` omits
                        content entirely.
                    paths_only: Return only location and classification fields.
                    allow_weak: Return the weak ranked pool even when the
                        post-rank abstention gate would return no_match.

                Returns:
                    A JSON object with ``results`` and ``freshness``.
                """
                start = time.monotonic()
                from code_search.engine.search import (
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
                # Same bounded cold-start wait as the daemon: prefer the warm
                # fused ranking over a silently different lexical-only one.
                wait_warm = getattr(comps.get("embedding_gen"), "wait_warm", None)
                if callable(wait_warm) and settings.warmup_wait_s > 0 and not no_model:
                    with suppress(Exception):
                        wait_warm(settings.warmup_wait_s)
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
                    regex=regex,
                    allow_weak=allow_weak,
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
                if compact:
                    from code_search.engine.response_service import compact_results

                    redacted = compact_results(
                        redacted,
                        10 if max_snippet_lines is None else max_snippet_lines,
                        paths_only=paths_only,
                    )
                from code_search.engine.response_service import relativize_results

                result_root = comps["metadata"].get("index_root") or str(
                    Path(comps["context_dir"]).parent
                )
                redacted = relativize_results(redacted, result_root)

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
                if count_field != "total_matches":
                    response["total_matches"] = total
                if envelope.get("token_savings") is not None:
                    response["token_savings"] = envelope["token_savings"]
                if envelope.get("content") is not None:
                    response["content"] = envelope["content"]
                for count_key in ("production_matches", "test_matches"):
                    if envelope.get(count_key) is not None:
                        response[count_key] = envelope[count_key]
                if envelope.get("scope") is not None:
                    response["scope"] = envelope["scope"]
                if envelope.get("matching_semantics") is not None:
                    response["matching_semantics"] = envelope["matching_semantics"]
                if envelope.get("regex"):
                    response["regex"] = True
                if envelope.get("pattern") is not None:
                    response["pattern"] = envelope["pattern"]
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
                from code_search.engine.index_service import IndexChangeDetector
                from code_search.engine.response_service import build_response

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
                    comps.get("db"),
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

            def _graph_service() -> Any:
                """Build a graph-query service over the shared components."""
                from code_search.engine.graph_query import GraphQueryService

                return GraphQueryService(
                    comps["db"],
                    comps["symbol_store"],
                    comps["edge_store"],
                    comps["search"],
                    settings,
                    reranker=comps.get("reranker"),
                )

            def _edge_types(value: str) -> set[str]:
                """Parse a comma-separated edge-type argument."""
                return {part.strip().upper() for part in value.split(",") if part.strip()}

            def _index_root() -> Path:
                """Return the indexed repository root recorded in metadata."""
                return Path(
                    comps["metadata"].get("index_root") or str(Path(comps["context_dir"]).parent)
                )

            @mcp.tool()
            async def get_graph_schema(
                diagnostics: bool = False,
                limit: int = 100,
                offset: int = 0,
            ) -> str:
                """Describe the graph before querying it.

                Reports stored node labels, supported and emitted edge types,
                resolution tiers, unresolved targets, symbol totals, coverage
                gaps, and the index generation. Call this first when you do not
                know which labels or edge types exist.

                Args:
                    diagnostics: Include bounded edge-property diagnostics.
                    limit: Maximum node labels returned (clipped to 500).
                    offset: Zero-based offset into the sorted node-label list.

                Returns:
                    A JSON payload with the schema sections and freshness.
                """
                start = time.monotonic()
                from code_search.engine.graph_surface import get_graph_schema

                payload = get_graph_schema(
                    comps["db"],
                    diagnostics=diagnostics,
                    node_limit=limit,
                    offset=offset,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="get_graph_schema",
                    query_summary="schema",
                    result_count=int(payload.get("node_labels_total", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def get_file_outline(
                file_path: str,
                kind: str = "",
                limit: int = 200,
                offset: int = 0,
                include_docstring: bool = False,
            ) -> str:
                """List one indexed file's declarations in source order.

                Use this to find declarations without grepping: it returns the
                exact symbol names, kinds, FQNs, and line ranges stored in the
                graph. An unindexed file returns ``outcome: not_indexed`` rather
                than an empty list.

                Args:
                    file_path: Absolute or index-relative path to the file.
                    kind: Optional comma-separated declaration kinds.
                    limit: Maximum declarations returned (clipped to 500).
                    offset: Zero-based offset into the declaration list.
                    include_docstring: Include stored docstrings (off by default).

                Returns:
                    A JSON payload with ``symbols``, exact ``total``, paging, and
                    freshness.
                """
                start = time.monotonic()
                from code_search.engine.graph_surface import get_file_outline

                kinds = [part.strip() for part in kind.split(",") if part.strip()] or None
                payload = get_file_outline(
                    comps["db"],
                    file_path,
                    index_root=_index_root(),
                    kinds=kinds,
                    limit=limit,
                    offset=offset,
                    include_docstring=include_docstring,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="get_file_outline",
                    query_summary=file_path[: settings.query_summary_length],
                    result_count=int(payload.get("returned", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def check_index_coverage(
                paths: list[str] | None = None,
                scopes: list[str] | None = None,
                max_rows: int = 500,
            ) -> str:
                """Report where the index has gaps before trusting a negative answer.

                Use this when a symbol, caller, or path seems missing: it
                distinguishes ``no_recorded_issue`` from ``partial``,
                ``unusable``, ``skipped``, ``excluded``, ``not_indexed``, and
                ``coverage_unavailable``. A clean result is not proof of
                completeness.

                Args:
                    paths: Optional absolute or index-relative file paths.
                    scopes: Optional index-relative directory prefixes.
                    max_rows: Row cap (clipped to 1000).

                Returns:
                    A JSON payload with per-path entries, per-scope aggregates,
                    a summary, freshness, and a recommended action.
                """
                start = time.monotonic()
                from code_search.engine.graph_surface import check_index_coverage as run_check

                payload = run_check(
                    comps["db"],
                    paths=paths,
                    scopes=scopes,
                    index_root=_index_root(),
                    parser=comps.get("parser"),
                    max_rows=max_rows,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="check_index_coverage",
                    query_summary=", ".join([*(paths or []), *(scopes or [])])[
                        : settings.query_summary_length
                    ]
                    or "all",
                    result_count=int(payload.get("summary", {}).get("returned", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def search_symbols(
                query: str | None = None,
                name_pattern: str | None = None,
                qn_pattern: str | None = None,
                kind: str = "",
                file_pattern: str | None = None,
                min_degree: int | None = None,
                max_degree: int | None = None,
                edge_types: str = "CALLS,INHERITS,IMPLEMENTS,REFERENCES,USAGE,CALL_REFERENCE",
                exclude_entry_points: bool = True,
                include_connected: bool = False,
                limit: int = 50,
                offset: int = 0,
            ) -> str:
                """Search symbols by structure instead of text similarity.

                Answers questions like "classes in src/api", "functions with zero
                callers", or "symbols matching .*Service". Degree counts resolved
                edges only; unresolved references never inflate a degree.
                Classified entry points (tests, main, constructors, overrides,
                annotated handlers, and exported top-level declarations) are
                excluded by default. Set exclude_entry_points=false to include
                them.

                Args:
                    query: Optional substring over name, FQN, and docstring.
                    name_pattern: Optional Python regex, full-match on the name.
                    qn_pattern: Optional Python regex, full-match on the FQN.
                    kind: Optional comma-separated declaration kinds.
                    file_pattern: Optional glob (or ``re:<regex>``) over the path.
                    min_degree: Minimum resolved total degree.
                    max_degree: Maximum resolved total degree.
                    edge_types: Comma-separated edge types counted for degree.
                    exclude_entry_points: Exclude tests, main, and constructors.
                    include_connected: Attach up to 10 resolved neighbours.
                    limit: Maximum symbols returned (clipped to 200).
                    offset: Zero-based offset into the ordered matches.

                Returns:
                    A JSON payload with symbols, exact total, paging, echoed
                    filters, generation, and a coverage caveat.
                """
                start = time.monotonic()
                from code_search.engine.graph_surface import search_symbols as run_search

                payload = run_search(
                    comps["db"],
                    query=query,
                    name_pattern=name_pattern,
                    qn_pattern=qn_pattern,
                    kind=kind,
                    file_pattern=file_pattern,
                    min_degree=min_degree,
                    max_degree=max_degree,
                    edge_types=sorted(_edge_types(edge_types)),
                    exclude_entry_points=exclude_entry_points,
                    include_connected=include_connected,
                    limit=limit,
                    offset=offset,
                    index_root=_index_root(),
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="search_symbols",
                    query_summary=(query or name_pattern or "symbols")[
                        : settings.query_summary_length
                    ],
                    result_count=int(payload.get("returned", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def find_dead_code(
                kinds: str = "function,method,constructor",
                include_entry_points: bool = False,
                include_tests: bool = False,
                limit: int = 50,
                offset: int = 0,
            ) -> str:
                """Report callables with no proven production reference.

                Candidates have zero incoming resolved CALLS, USAGE,
                CALL_REFERENCE, REFERENCES, IMPLEMENTS, or INHERITS edges from
                non-test symbols. Entry points and test symbols are excluded by
                default. Every row reports test-only usage and same-name
                unresolved references, because those are the cases where a
                dynamic or external caller could keep the symbol alive.

                This tool reports evidence, not permission to delete code.
                Check ``check_index_coverage`` when a negative answer matters.

                Args:
                    kinds: Comma-separated candidate kinds.
                    include_entry_points: Include classified entry points.
                    include_tests: Include test symbols as candidates.
                    limit: Maximum candidates returned (clipped to 200).
                    offset: Zero-based offset into the ordered candidates.

                Returns:
                    A JSON payload with candidates, exact total, paging,
                    confidence, and the edge types checked.
                """
                start = time.monotonic()
                from code_search.engine.graph_surface import find_dead_code as run_dead_code

                payload = run_dead_code(
                    comps["db"],
                    kinds=kinds,
                    include_entry_points=include_entry_points,
                    include_tests=include_tests,
                    limit=limit,
                    offset=offset,
                    index_root=_index_root(),
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="find_dead_code",
                    query_summary=kinds[: settings.query_summary_length],
                    result_count=int(payload.get("returned", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def get_architecture(
                aspects: str = "overview",
                top_n: int = 15,
                max_communities: int = 10,
            ) -> str:
                """Return a bounded architecture summary of the indexed graph.

                The default ``overview`` aspect is deliberately small: languages,
                directory packages, and entry-point counts. Request only the
                sections you need; ``all`` expands to every section and can be
                large.

                Aspects: ``overview``, ``structure``, ``dependencies``,
                ``hotspots``, ``entry_points``, ``clusters``, ``cycles``.

                Args:
                    aspects: Comma-separated aspect names, or ``all``.
                    top_n: Maximum hotspots/packages/examples (clipped to 50).
                    max_communities: Maximum clusters returned (clipped to 20).

                Returns:
                    A JSON payload with the requested sections, generation,
                    stats, and freshness.
                """
                start = time.monotonic()
                requested = {part.strip().lower() for part in aspects.split(",") if part.strip()}
                payload = _graph_service().architecture(
                    aspects=requested or None,
                    top_n=top_n,
                    max_communities=max_communities,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="get_architecture",
                    query_summary=", ".join(sorted(requested)) or "overview",
                    result_count=len(payload.get("hotspots") or []),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def query_graph(
                question: str,
                depth: int = 2,
                max_nodes: int = 120,
                token_budget: int = 1500,
                edge_types: str = "CALLS,INHERITS",
                include_external: bool = False,
                direction: str = "both",
            ) -> str:
                """Answer a multi-hop question by traversing the code graph.

                Seeds come from the existing hybrid search ranker; the answer is
                a bounded neighbourhood rendered as compact structured JSON with
                a confidence label on every edge.

                Args:
                    question: Natural-language or identifier question.
                    depth: Traversal depth (clipped to 4).
                    max_nodes: Maximum returned nodes (clipped to 200).
                    token_budget: Soft output token budget.
                    edge_types: Comma-separated edge types to traverse.
                    include_external: Include unresolved/external callee leaves;
                        false (default) collapses them so the answer is a clean
                        in-corpus neighbourhood.
                    direction: ``both`` (default), ``inbound`` (who calls/imports
                        this), or ``outbound`` (what this calls/imports).

                Returns:
                    A JSON payload with seeds, nodes, edges, truncation, stats,
                    direction, and freshness.
                """
                start = time.monotonic()
                answer = _graph_service().query(
                    question,
                    depth=depth,
                    max_nodes=max_nodes,
                    edge_types=_edge_types(edge_types),
                    token_budget=token_budget,
                    include_external=include_external,
                    direction=direction,
                )
                payload = answer.as_dict()
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="query_graph",
                    query_summary=question[: settings.query_summary_length],
                    result_count=len(answer.nodes),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def shortest_path(
                source: str,
                target: str,
                undirected: bool = False,
                max_hops: int = 6,
                edge_types: str = "CALLS,INHERITS",
            ) -> str:
                """Return the shortest graph path between two symbols.

                Ambiguous endpoints are refused with ranked candidates rather
                than guessed.

                Args:
                    source: Source symbol reference.
                    target: Target symbol reference.
                    undirected: Traverse edges in both directions.
                    max_hops: Maximum path length (clipped to 6).
                    edge_types: Comma-separated edge types to traverse.

                Returns:
                    A JSON payload with source, target, hops, outcome, and
                    freshness.
                """
                start = time.monotonic()
                answer = _graph_service().shortest_path(
                    source,
                    target,
                    undirected=undirected,
                    max_hops=max_hops,
                    edge_types=_edge_types(edge_types),
                )
                payload = answer.as_dict()
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="shortest_path",
                    query_summary=f"{source} -> {target}"[: settings.query_summary_length],
                    result_count=len(answer.hops),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def explain_symbol(
                symbol: str,
                depth: int = 1,
                relations: str = "CALLS,INHERITS",
            ) -> str:
                """Explain a symbol: metadata, incoming/outgoing relations,
                rationale comments, and linked documentation.

                Args:
                    symbol: Symbol reference.
                    depth: Ego-graph depth (clipped to 4).
                    relations: Comma-separated relations to include.

                Returns:
                    A JSON payload with the symbol, nodes, edges, rationale,
                    doc links, and freshness.
                """
                start = time.monotonic()
                answer = _graph_service().explain(
                    symbol, depth=depth, relations=_edge_types(relations)
                )
                payload = answer.as_dict()
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="explain_symbol",
                    query_summary=symbol[: settings.query_summary_length],
                    result_count=1 if answer.symbol else 0,
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def get_impact(changed_paths: list[str], depth: int = 3) -> str:
                """Return symbols impacted by a set of changed files.

                Args:
                    changed_paths: Absolute or index-relative changed paths.
                    depth: Reverse traversal depth (clipped to 4).

                Returns:
                    A JSON payload with changed paths, impacted symbols grouped
                    by file, and a summary.
                """
                start = time.monotonic()
                answer = _graph_service().impact(changed_paths, depth=depth)
                payload = answer.as_dict()
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="get_impact",
                    query_summary=", ".join(changed_paths)[: settings.query_summary_length],
                    result_count=len(answer.impacted),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

            @mcp.tool()
            async def detect_changes(
                changed_paths: list[str] | None = None,
                since: str | None = None,
                base_branch: str | None = None,
                scope: str = "impact",
                direction: str = "inbound",
                depth: int = 3,
                fixpoint: bool = False,
                edge_types: str = "CALLS,INHERITS",
                include_imports: bool = True,
                seed_filter: str = "all",
                max_nodes: int = 200,
            ) -> str:
                """Resolve changed files (optionally from git) and report impact.

                Use ``scope="files"`` when you only need the changed path set,
                ``scope="impact"`` for the full blast radius, and
                ``scope="tests"`` for the test files and test symbols that
                reach the change. ``direction="inbound"`` answers "what depends
                on this"; ``outbound`` answers "what does this depend on".

                Args:
                    changed_paths: Explicit changed paths.
                    since: Git ref to diff against.
                    base_branch: Base branch/ref (takes precedence over since).
                    scope: ``files``, ``impact``, or ``tests``.
                    direction: ``inbound``, ``outbound``, or ``both``.
                    depth: Traversal depth (clipped to 4).
                    fixpoint: Walk to closure instead of stopping at depth.
                    edge_types: Comma-separated symbol edge types to traverse.
                    include_imports: Traverse file-level import edges too.
                    seed_filter: ``all`` or ``product`` (drop test-file seeds).
                    max_nodes: Maximum returned nodes (clipped to 200).

                Returns:
                    A JSON payload with changed files, impacted symbols with
                    risk labels, production/test buckets, traversal provenance,
                    generation, and freshness.
                """
                start = time.monotonic()
                result = _graph_service().detect_changes(
                    changed_paths or [],
                    since=since,
                    base_branch=base_branch,
                    scope=scope,
                    direction=direction,
                    depth=depth,
                    fixpoint=fixpoint,
                    edge_types=_edge_types(edge_types),
                    include_imports=include_imports,
                    seed_filter=seed_filter,
                    max_nodes=max_nodes,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                result["index_status"] = comps["metadata"].get_index_status()
                result["query_time_ms"] = duration_ms
                result["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="detect_changes",
                    query_summary=(
                        base_branch or since or ", ".join(changed_paths or []) or "no_changes"
                    )[: settings.query_summary_length],
                    result_count=int(result.get("summary", {}).get("symbols", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(result, default=str)

            @mcp.tool()
            async def cypher_query(
                query: str,
                limit: int = 100,
                offset: int = 0,
                cursor: str = "",
                timeout_ms: int = 5000,
            ) -> str:
                """Run a read-only Cypher subset over the indexed code graph.

                Use this for precise multi-hop and aggregate questions that the
                fixed graph tools do not cover, for example callers/callees,
                inheritance chains, unresolved targets, and dead-code
                predicates with ``EXISTS``.

                This is not ``query_graph``: ``query_graph`` takes a
                natural-language question and returns a bounded, search-seeded
                neighbourhood. ``cypher_query`` takes an explicit graph query
                and returns tabular rows.

                Supported: ``MATCH``/``OPTIONAL MATCH``, ``WHERE``, ``WITH``,
                ``UNWIND``, ``RETURN``, ``ORDER BY``/``SKIP``/``LIMIT``,
                ``DISTINCT``, ``UNION``, ``CASE``, labelled nodes, directed
                relationships, ``[*1..5]`` paths, inline property maps,
                ``EXISTS { ... }``, aggregates (``count``/``sum``/``avg``/
                ``min``/``max``/``collect``), and string/scalar functions.
                Labels: ``Function``, ``Method``, ``Class``, ``Interface``,
                ``Enum``, ``Constructor``, ``Field``, ``Variable``, ``Import``,
                ``TypeAlias``, plus synthetic ``File``, ``Module``,
                ``Unresolved``, and structural ``CONTAINS`` edges. A
                ``UNION`` applies the final ``RETURN``'s ``ORDER BY``/``LIMIT``.

                The statement is read-only, parameterized, and bounded by
                ``limit``, ``timeout_ms``, and a byte cap. Page with the
                ``next_cursor`` value; a cursor is valid only for the same index
                generation and query text. An empty result is not proof that
                the code is absent — check ``check_index_coverage``.

                Args:
                    query: Cypher query text.
                    limit: Maximum rows returned (clipped to 500).
                    offset: Row offset; ignored when ``cursor`` is set.
                    cursor: Cursor from the previous page (generation-keyed).
                    timeout_ms: Wall-clock deadline (clipped to 1..30000).

                Returns:
                    A JSON payload with ``columns``, ``rows``, paging,
                    generation, digest, timing, and a trust note. Invalid or
                    unsupported syntax returns ``outcome: invalid_argument``
                    with an ``error_kind`` and a message; an expired deadline
                    returns ``outcome: timeout``.
                """
                start = time.monotonic()
                from code_search.engine.cypher import execute_cypher

                payload = execute_cypher(
                    comps["db"],
                    query,
                    limit=limit,
                    offset=offset,
                    cursor=cursor,
                    timeout_ms=timeout_ms,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                payload["index_status"] = comps["metadata"].get_index_status()
                payload["query_time_ms"] = duration_ms
                payload["freshness"] = _freshness_signal(comps)
                audit_db.write_entry(
                    query_type="cypher_query",
                    query_summary=query[: settings.query_summary_length],
                    result_count=int(payload.get("row_count", 0)),
                    duration_ms=duration_ms,
                    redacted_count=0,
                )
                if mc:
                    mc.record_query(duration_ms)
                return json.dumps(payload, default=str)

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
                from code_search.engine.response_service import relativize_results

                result_root = comps["metadata"].get("index_root") or str(
                    Path(comps["context_dir"]).parent
                )
                results = relativize_results(results, result_root)
                data["results"] = results
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
                return json.dumps(data, default=str)

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
        from code_search.engine.redactor import air_gap_enforcement

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
