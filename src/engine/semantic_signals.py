"""Semantic signal computation for find_related relevance ranking.

This module computes three semantic signals from the existing index data:
1. Package overlap - Jaccard similarity of directory path segments
2. Type sharing - Normalized signature overlap (parameters + return types)
3. Call graph proximity - Inverse shortest path distance in CALLS graph

These signals are combined with vector similarity via weighted fusion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.symbol_resolution import normalize_signature

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticSignals:
    """Computed semantic signals between anchor and candidate."""

    package_overlap: float
    type_sharing: float
    call_proximity: float

    def __post_init__(self) -> None:
        for field_name in ("package_overlap", "type_sharing", "call_proximity"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be in [0.0, 1.0], got {value}")


@dataclass(frozen=True)
class RelevanceScore:
    """Final combined relevance score."""

    semantic_score: float
    vector_score: float
    final_score: float

    def __post_init__(self) -> None:
        for field_name in ("semantic_score", "vector_score", "final_score"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be in [0.0, 1.0], got {value}")


# Segments that terminate the language source tree. Everything after the last
# such marker is the code's own namespace (e.g. ``com.example.article``), so
# package overlap is measured over namespace segments rather than over the
# absolute path whose shared scaffolding (repo root, ``src/main/java``) would
# inflate unrelated packages into near-matches.
_SOURCE_ROOT_MARKERS = frozenset({"src", "source", "java", "kotlin", "scala", "groovy"})


def _package_segments(file_path: str) -> set[str]:
    """Extract the language-namespace directory segments of *file_path*.

    Drops the source-root scaffolding (repo root, ``src/main/java``) so two
    files in unrelated packages do not score as package neighbours purely
    because they share the corpus's absolute prefix. Falls back to the full
    directory set when no source-root marker is present.

    Args:
        file_path: Absolute or project-relative file path.

    Returns:
        Set of namespace directory segments (filename excluded).
    """
    parent_parts = Path(file_path).parent.parts
    last_marker = -1
    for i, segment in enumerate(parent_parts):
        if segment in _SOURCE_ROOT_MARKERS:
            last_marker = i
    if last_marker >= 0:
        return {segment for segment in parent_parts[last_marker + 1 :] if segment}
    return {segment for segment in parent_parts if segment and segment != "/"}


def compute_package_overlap(anchor_path: str, candidate_path: str) -> float:
    """Compute package overlap score using Jaccard similarity of namespace segments.

    Args:
        anchor_path: Anchor symbol's file path
        candidate_path: Candidate symbol's file path

    Returns:
        Jaccard similarity in [0.0, 1.0]
    """
    anchor_segments = _package_segments(anchor_path)
    candidate_segments = _package_segments(candidate_path)

    if not anchor_segments and not candidate_segments:
        return 1.0
    if not anchor_segments or not candidate_segments:
        return 0.0

    intersection = anchor_segments & candidate_segments
    union = anchor_segments | candidate_segments

    return len(intersection) / len(union) if union else 0.0


def _extract_type_tokens(signature: dict[str, Any] | None) -> set[str]:
    """Extract normalized type tokens from a signature dict."""
    if not signature:
        return set()
    types: set[str] = set()
    for param_type in signature.get("param_types", []):
        base_type = re.sub(r"[<>\[\],].*", "", param_type).strip()
        if base_type:
            types.add(base_type.lower())
    return types


def compute_type_sharing(anchor_fqn: str, candidate_fqn: str) -> float:
    """Compute type sharing score between two symbols.

    Uses normalized signature comparison (parameters + return type).
    Score = |shared_types| / max(|anchor_types|, |candidate_types|)
    Bonus +0.2 if return types match, capped at 1.0.

    Args:
        anchor_fqn: Anchor symbol's fully qualified name
        candidate_fqn: Candidate symbol's fully qualified name

    Returns:
        Type sharing score in [0.0, 1.0]
    """
    anchor_sig = normalize_signature(anchor_fqn)
    candidate_sig = normalize_signature(candidate_fqn)

    anchor_types = _extract_type_tokens(anchor_sig)
    candidate_types = _extract_type_tokens(candidate_sig)

    if not anchor_types and not candidate_types:
        return 0.0
    if not anchor_types or not candidate_types:
        return 0.0

    shared = anchor_types & candidate_types
    max_types = max(len(anchor_types), len(candidate_types))

    score = len(shared) / max_types if max_types > 0 else 0.0

    anchor_return = anchor_sig.get("return_type", "").lower() if anchor_sig else ""
    candidate_return = candidate_sig.get("return_type", "").lower() if candidate_sig else ""
    if anchor_return and candidate_return and anchor_return == candidate_return:
        score = min(1.0, score + 0.2)

    return score


def _call_proximity_from_depth(depth: int | None) -> float:
    """Score a call-graph depth (1.0 / depth for depth <= 3, else 0.0)."""
    if depth in (1, 2, 3):
        return 1.0 / depth
    return 0.0


def _fetch_call_depths(db: GraphDatabase, anchor_symbol_id: int, max_depth: int) -> dict[int, int]:
    """Return {symbol_id: shortest_depth} for all CALLS neighbours of the anchor.

    Executes one recursive CTE per direction (callers then callees) for the
    whole anchor instead of one CTE pair per candidate, so reranking a pool of
    dozens of candidates stays within the latency budget.

    Args:
        db: Graph database connection
        anchor_symbol_id: Anchor symbol ID
        max_depth: Maximum traversal depth

    Returns:
        Mapping of neighbour symbol id -> shortest caller/callee depth
    """
    depths: dict[int, int] = {}
    if anchor_symbol_id is None:
        return depths

    def _merge(rows: list[Any]) -> None:
        for row in rows:
            nid = int(row["nid"])
            depth = int(row["depth"])
            if nid not in depths or depth < depths[nid]:
                depths[nid] = depth

    try:
        with db.connect() as conn:
            # Callers: symbols that transitively reach the anchor via CALLS.
            caller_rows = conn.execute(
                "WITH RECURSIVE callers(nid, depth, path) AS ( "
                "SELECT e.source_symbol_id AS nid, 1 AS depth, "
                "'|' || e.source_symbol_id || '|' AS path "
                "FROM graph_edges e "
                "WHERE e.target_symbol_id = ? AND e.edge_type = 'CALLS' "
                "UNION ALL "
                "SELECT e.source_symbol_id, c.depth + 1, c.path || e.source_symbol_id || '|' "
                "FROM graph_edges e "
                "JOIN callers c ON e.target_symbol_id = c.nid "
                "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
                "AND instr(c.path, '|' || e.source_symbol_id || '|') = 0 "
                ") "
                "SELECT nid, MIN(depth) AS depth FROM callers GROUP BY nid;",
                (anchor_symbol_id, max_depth),
            ).fetchall()
            _merge(caller_rows)

            # Callees: symbols reachable from the anchor via CALLS.
            callee_rows = conn.execute(
                "WITH RECURSIVE callees(nid, depth, path) AS ( "
                "SELECT e.target_symbol_id AS nid, 1 AS depth, "
                "'|' || e.target_symbol_id || '|' AS path "
                "FROM graph_edges e "
                "WHERE e.source_symbol_id = ? AND e.edge_type = 'CALLS' "
                "AND e.target_symbol_id IS NOT NULL "
                "UNION ALL "
                "SELECT e.target_symbol_id, c.depth + 1, c.path || e.target_symbol_id || '|' "
                "FROM graph_edges e "
                "JOIN callees c ON e.source_symbol_id = c.nid "
                "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
                "AND e.target_symbol_id IS NOT NULL "
                "AND instr(c.path, '|' || e.target_symbol_id || '|') = 0 "
                ") "
                "SELECT nid, MIN(depth) AS depth FROM callees GROUP BY nid;",
                (anchor_symbol_id, max_depth),
            ).fetchall()
            _merge(callee_rows)
    except Exception as exc:
        logger.warning("Call graph depth fetch failed: %s", exc)

    return depths


def compute_call_proximity(
    db: GraphDatabase, anchor_symbol_id: int, candidate_symbol_id: int, max_depth: int = 3
) -> float:
    """Compute call graph proximity score.

    Score = 1.0/depth for depth in {1, 2, 3}, else 0.0
    Searches both directions (callers and callees).

    Args:
        db: Graph database connection
        anchor_symbol_id: Anchor symbol ID
        candidate_symbol_id: Candidate symbol ID
        max_depth: Maximum traversal depth (default 3)

    Returns:
        Call proximity score in [0.0, 1.0]
    """
    if anchor_symbol_id == candidate_symbol_id:
        return 1.0

    try:
        with db.connect() as conn:
            # Search callers (reverse direction)
            rows = conn.execute(
                "WITH RECURSIVE callers AS ( "
                "SELECT e.source_symbol_id AS caller_id, 1 AS depth, "
                "'|' || e.source_symbol_id || '|' AS path "
                "FROM graph_edges e "
                "WHERE e.target_symbol_id = ? AND e.edge_type = 'CALLS' "
                "UNION ALL "
                "SELECT e.source_symbol_id, c.depth + 1, "
                "c.path || e.source_symbol_id || '|' "
                "FROM graph_edges e "
                "JOIN callers c ON e.target_symbol_id = c.caller_id "
                "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
                "AND instr(c.path, '|' || e.source_symbol_id || '|') = 0 "
                ") "
                "SELECT depth FROM callers WHERE caller_id = ? "
                "ORDER BY depth LIMIT 1;",
                (anchor_symbol_id, max_depth, candidate_symbol_id),
            ).fetchall()

            for row in rows:
                depth = int(row["depth"])
                if 1 <= depth <= 3:
                    return 1.0 / depth

            # Search callees (forward direction)
            rows = conn.execute(
                "WITH RECURSIVE callees AS ( "
                "SELECT e.target_symbol_id AS callee_id, 1 AS depth, "
                "'|' || e.target_symbol_id || '|' AS path "
                "FROM graph_edges e "
                "WHERE e.source_symbol_id = ? AND e.edge_type = 'CALLS' "
                "UNION ALL "
                "SELECT e.target_symbol_id, c.depth + 1, "
                "c.path || e.target_symbol_id || '|' "
                "FROM graph_edges e "
                "JOIN callees c ON e.source_symbol_id = c.callee_id "
                "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
                "AND instr(c.path, '|' || e.target_symbol_id || '|') = 0 "
                ") "
                "SELECT depth FROM callees WHERE callee_id = ? "
                "ORDER BY depth LIMIT 1;",
                (anchor_symbol_id, max_depth, candidate_symbol_id),
            ).fetchall()

            for row in rows:
                depth = int(row["depth"])
                if 1 <= depth <= 3:
                    return 1.0 / depth

    except Exception as exc:
        logger.warning("Call proximity query failed: %s", exc)

    return 0.0


def compute_semantic_score(
    anchor: dict[str, Any],
    candidate: dict[str, Any],
    db: GraphDatabase,
    max_call_depth: int = 3,
    call_depths: dict[int, int] | None = None,
) -> SemanticSignals:
    """Compute all three semantic signals for a candidate.

    Args:
        anchor: Anchor symbol dict with fqn, file_path, symbol_id
        candidate: Candidate symbol dict with fqn, file_path, symbol_id
        db: Graph database
        max_call_depth: Maximum call graph traversal depth
        call_depths: Optional precomputed {symbol_id: depth} map for the anchor
            (avoids one CTE pair per candidate during reranking)

    Returns:
        SemanticSignals with all three scores
    """
    pkg_score = compute_package_overlap(anchor["file_path"], candidate["file_path"])
    type_score = compute_type_sharing(anchor["fqn"], candidate["fqn"])

    if call_depths is not None and candidate.get("symbol_id") is not None:
        if anchor.get("symbol_id") is not None and (candidate["symbol_id"] == anchor["symbol_id"]):
            call_score = 1.0
        else:
            call_score = _call_proximity_from_depth(call_depths.get(candidate["symbol_id"]))
    else:
        call_score = compute_call_proximity(
            db, anchor["symbol_id"], candidate["symbol_id"], max_call_depth
        )

    return SemanticSignals(
        package_overlap=pkg_score, type_sharing=type_score, call_proximity=call_score
    )


def compute_final_score(
    semantic_signals: SemanticSignals,
    vector_similarity: float,
    weights: dict[str, float],
    semantic_blend: float,
) -> RelevanceScore:
    """Compute final relevance score from semantic signals and vector similarity.

    semantic_score = w_pkg * pkg + w_type * type + w_call * call
    final_score = semantic_blend * semantic_score + (1 - semantic_blend) * vector_similarity

    Args:
        semantic_signals: Computed semantic signals
        vector_similarity: Cosine similarity from vector search [0.0, 1.0]
        weights: Dict with keys 'package', 'type', 'call_graph'
        semantic_blend: Alpha parameter in [0.0, 1.0]

    Returns:
        RelevanceScore with semantic, vector, and final scores
    """
    semantic_score = (
        weights["package"] * semantic_signals.package_overlap
        + weights["type"] * semantic_signals.type_sharing
        + weights["call_graph"] * semantic_signals.call_proximity
    )

    final_score = semantic_blend * semantic_score + (1.0 - semantic_blend) * vector_similarity

    return RelevanceScore(
        semantic_score=semantic_score, vector_score=vector_similarity, final_score=final_score
    )


def _is_structural_false_positive(
    semantic_signals: SemanticSignals,
    vector_similarity: float,
    threshold: float = 0.15,
    vector_threshold: float = 0.7,
) -> bool:
    """Detect structural false positive: high vector similarity but low semantic relevance.

    Candidates with semantic score < 0.15 AND vector similarity > 0.7
    are structural false positives (e.g., classes sharing only annotations).

    Args:
        semantic_signals: Computed semantic signals
        vector_similarity: Vector cosine similarity
        threshold: Semantic score threshold (default 0.15)
        vector_threshold: Vector similarity threshold (default 0.7)

    Returns:
        True if candidate is a structural false positive
    """
    semantic_score = (
        semantic_signals.package_overlap * 0.3
        + semantic_signals.type_sharing * 0.3
        + semantic_signals.call_proximity * 0.4
    )
    return semantic_score < threshold and vector_similarity > vector_threshold


_TYPE_LIKE_KINDS = frozenset({"class", "interface", "enum", "record", "struct"})


def _anchor_call_roots(conn: Any, anchor_symbol_id: int, anchor_kind: str | None) -> list[int]:
    """Return the symbol ids whose call graphs represent the anchor.

    CALLS edges link *method* symbols, so anchoring on a class/interface/enum
    would otherwise score zero call proximity for every candidate. Expand such
    anchors to their member methods (callers/callees of any member count).

    Args:
        conn: Open database connection.
        anchor_symbol_id: Anchor symbol id.
        anchor_kind: Anchor symbol kind (``class``, ``method``, ...).

    Returns:
        List of root symbol ids to traverse (the anchor plus its methods).
    """
    roots = [anchor_symbol_id]
    if anchor_kind and anchor_kind in _TYPE_LIKE_KINDS:
        rows = conn.execute(
            "SELECT id FROM symbols WHERE parent_symbol_id = ? "
            "AND kind IN ('method', 'constructor', 'function');",
            (anchor_symbol_id,),
        ).fetchall()
        roots.extend(int(r["id"]) for r in rows)
    return roots


def rerank_with_semantic(
    vector_results: list[tuple[int, float]],
    anchor: dict[str, Any],
    db: GraphDatabase,
    settings: Settings,
    limit: int,
) -> list[dict[str, Any]]:
    """Rerank vector search results using semantic signals.

    Args:
        vector_results: List of (chunk_id, vector_similarity) from vector search
        anchor: Anchor symbol dict with fqn, file_path, symbol_id
        db: Graph database
        settings: Engine settings with semantic weights
        limit: Maximum results to return

    Returns:
        List of result dicts with final_score and semantic_signals, sorted by final_score desc
    """
    weights = {
        "package": settings.find_related_weight_package,
        "type": settings.find_related_weight_type,
        "call_graph": settings.find_related_weight_call_graph,
    }
    semantic_blend = settings.find_related_semantic_blend
    max_call_depth = settings.max_graph_depth

    if semantic_blend == 0.0:
        return []

    results = []
    # Cache the anchor's whole call graph once (callers + callees up to
    # max_call_depth) so per-candidate proximity is a dict lookup, not a pair
    # of recursive CTE queries per candidate. A type-like anchor expands to its
    # member methods so class/entity anchors keep a usable call signal.
    call_depths: dict[int, int] = {}
    anchor_symbol_id = anchor.get("symbol_id")
    if anchor_symbol_id is not None:
        roots = [anchor_symbol_id]
        try:
            with db.connect() as conn:
                roots = _anchor_call_roots(conn, anchor_symbol_id, anchor.get("kind"))
        except Exception as exc:
            logger.warning("Anchor member expansion failed: %s", exc)
        for root in roots:
            for nid, depth in _fetch_call_depths(db, root, max_call_depth).items():
                if nid not in call_depths or depth < call_depths[nid]:
                    call_depths[nid] = depth

    with db.connect() as conn:
        for chunk_id, vector_sim in vector_results:
            if chunk_id == anchor.get("chunk_id"):
                continue

            row = conn.execute(
                "SELECT id, fqn, file_path FROM code_chunks WHERE id = ?;", (chunk_id,)
            ).fetchone()

            if not row:
                continue

            candidate_symbol_id = None
            sym_row = conn.execute(
                "SELECT id FROM symbols WHERE fqn = ?;", (row["fqn"],)
            ).fetchone()
            if sym_row:
                candidate_symbol_id = sym_row["id"]

            if not candidate_symbol_id:
                final_score = (1.0 - semantic_blend) * vector_sim
                results.append(
                    {
                        "chunk_id": chunk_id,
                        "fqn": row["fqn"],
                        "file_path": row["file_path"],
                        "vector_similarity": vector_sim,
                        "semantic_signals": SemanticSignals(0.0, 0.0, 0.0),
                        "final_score": final_score,
                        "symbol_id": None,
                    }
                )
                continue

            candidate = {
                "fqn": row["fqn"],
                "file_path": row["file_path"],
                "symbol_id": candidate_symbol_id,
            }

            signals = compute_semantic_score(
                anchor,
                candidate,
                db,
                max_call_depth,
                call_depths=call_depths,
            )

            relevance = compute_final_score(signals, vector_sim, weights, semantic_blend)

            if _is_structural_false_positive(signals, vector_sim):
                final_score = relevance.final_score * 0.5
            else:
                final_score = relevance.final_score

            results.append(
                {
                    "chunk_id": chunk_id,
                    "fqn": row["fqn"],
                    "file_path": row["file_path"],
                    "vector_similarity": vector_sim,
                    "semantic_signals": signals,
                    "final_score": final_score,
                    "symbol_id": candidate_symbol_id,
                }
            )

    results.sort(key=lambda r: r["final_score"], reverse=True)
    return results[:limit]
