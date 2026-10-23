"""Shared ``find-related`` anchor resolution and neighbour ranking.

Both the MCP tool and the CLI's daemon-forwarded path call :func:`find_related`
so the two surfaces resolve the anchor chunk with the same rule: the most
specific (smallest) chunk whose line range contains the requested line. The
returned payload has no transport concerns — the MCP server serializes it and
the daemon wraps it — so ``query_time_ms`` is the only timing field here.

The anchor chunk's own file is excluded from the neighbour set by default; when
that leaves no cross-file neighbour the response is explicitly labelled
``same_file_only`` or ``empty`` rather than presenting same-file self-chunks as
cross-file relatedness.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_search.engine.classification import FileRole, file_role
from code_search.engine.config import Settings
from code_search.engine.paths import normalize_indexed_path, resolve_stored_path
from code_search.engine.redactor import Redactor
from code_search.engine.semantic_signals import rerank_with_semantic


@dataclass(frozen=True)
class AnchorChunk:
    """The indexed chunk selected for a ``find-related`` anchor.

    Attributes:
        stored_path: The stored spelling of the resolved file path.
        chunk_id: Primary key of the anchor chunk in ``code_chunks``.
        fqn: Fully qualified symbol name of the chunk, when known.
        content: The chunk source text.
        language: Chunk language identifier.
        line_start: First source line covered by the chunk.
        line_end: Last source line covered by the chunk.
    """

    stored_path: str
    chunk_id: int
    fqn: str | None
    content: str
    language: str | None
    line_start: int
    line_end: int


def resolve_anchor_chunk(
    db: Any,
    file_path: str,
    line_number: int,
    index_root: Path,
) -> AnchorChunk | None:
    """Resolve *file_path* and locate the smallest chunk containing *line_number*.

    Anchoring the smallest containing chunk embeds a method body rather than the
    enclosing class, which keeps semantic signals (type sharing, call
    proximity) specific instead of degrading to package-level similarity.

    Args:
        db: The graph database.
        file_path: Absolute or project-relative file path supplied by the caller.
        line_number: Line within the file to anchor.
        index_root: Repository root used to normalise relative paths.

    Returns:
        The matching :class:`AnchorChunk`, or ``None`` when the file is not
        indexed or no chunk contains the line.
    """
    normalized = normalize_indexed_path(file_path, index_root)
    if normalized is None:
        return None
    with db.connect() as conn:
        stored_path = resolve_stored_path(normalized, conn)
        if stored_path is None:
            return None
        row = conn.execute(
            "SELECT id, fqn, content, language, line_start, line_end FROM code_chunks "
            "WHERE file_path = ? AND line_start <= ? AND line_end >= ? "
            "ORDER BY (line_end - line_start) ASC, line_start ASC "
            "LIMIT 1;",
            (stored_path, line_number, line_number),
        ).fetchone()
    if row is None:
        return None
    return AnchorChunk(
        stored_path=stored_path,
        chunk_id=int(row["id"]),
        fqn=row["fqn"],
        content=row["content"] or "",
        language=row["language"],
        line_start=int(row["line_start"]),
        line_end=int(row["line_end"]),
    )


def find_related(
    comps: dict[str, Any],
    file_path: str,
    line_number: int,
    limit: int,
) -> dict[str, Any]:
    """Return the chunks most related to the anchor at *file_path*:*line_number*.

    Args:
        comps: The shared component registry (``db``, ``metadata``,
            ``embedding_gen``, ``vector_index``, ``context_dir``, and optional
            ``settings``/``redactor``).
        file_path: Absolute or project-relative path to a file.
        line_number: Line within the file to anchor.
        limit: Maximum related chunks to return; capped at the configured
            ``find_related_limit``.

    Returns:
        A payload with ``results`` (anchor excluded), ``vector_health``,
        ``status`` (``cross_file``/``same_file_only``/``best_effort``/
        ``empty``), and ``query_time_ms`` — or an ``error`` payload when no
        indexed chunk contains the line.
    """
    start = time.monotonic()
    embedding_gen = comps["embedding_gen"]
    vector_index = comps["vector_index"]
    settings = comps.get("settings") or Settings.from_env()
    redactor = comps.get("redactor") or Redactor()

    def _payload(payload: dict[str, Any]) -> dict[str, Any]:
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        return payload

    index_root = Path(comps["context_dir"]).parent
    stored_root = comps["metadata"].get("index_root")
    if stored_root:
        index_root = Path(stored_root)

    anchor = resolve_anchor_chunk(comps["db"], file_path, line_number, index_root)
    if anchor is None:
        return _payload({"error": f"No indexed chunk found at '{file_path}:{line_number}'"})
    stored_path = anchor.stored_path
    anchor_id = anchor.chunk_id

    query_vec = embedding_gen.encode(anchor.content)
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
    # Directional boilerplate suppression — a non-boilerplate anchor excludes
    # scaffolding-shape neighbours (MODEL/DTO/ASSEMBLER/EXCEPTION) by default; a
    # genuine DTO/model anchor still finds its peers. Setting
    # ``CODE_SEARCH_FIND_RELATED_EXCLUDE_BOILERPLATE=false`` switches the
    # exclusion to a down-weight.
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

    # Fetch candidates before filtering so an anchor that is its own cosine
    # top-1 still yields a full limit of neighbours. Semantic reranking widens
    # the pool further so structurally close neighbours outside the pure-vector
    # top-(limit+1) can still be promoted.
    candidate_k = limit + 1
    if settings.find_related_semantic_blend > 0:
        candidate_k = max(candidate_k, limit + 50)
    search_results = vector_index.search(
        query_vec,
        top_k=candidate_k,
        exclude_file_paths={stored_path} if exclude_file else None,
    )

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

    if settings.find_related_semantic_blend > 0 and anchor_symbol_id:
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
            limit + 1,
        )
        search_results = [(r["chunk_id"], r["final_score"]) for r in semantic_reranked]

    def _build_results(
        scored: list[tuple[int, float]], same_file_flag: bool
    ) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
        """Return ``(kept_results, boilerplate_only, raw_results)``."""
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
            redacted_content, _redacted_count = redactor.redact(cr["content"] or "")
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
        # Rank by score before every branch so exclusion, down-weighting, and
        # the all-boilerplate path all return score-ordered rows.
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

    def _best_effort(rows: list[dict[str, Any]], same_file: bool) -> dict[str, Any]:
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
    # neighbours always outrank them.
    penalty = settings.find_related_same_file_penalty
    chunk_ids = [cid for cid, _ in search_results]
    placeholders = ",".join("?" for _ in chunk_ids)
    with comps["db"].connect() as conn:
        file_rows = conn.execute(
            f"SELECT id, file_path FROM code_chunks WHERE id IN ({placeholders});",
            chunk_ids,
        ).fetchall()
    file_by_id = {r["id"]: r["file_path"] for r in file_rows}
    cross_scored: list[tuple[int, float]] = []
    same_scored: list[tuple[int, float]] = []
    for cid, score in search_results:
        if cid == anchor_id:
            continue
        if file_by_id.get(cid, "") == stored_path:
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
