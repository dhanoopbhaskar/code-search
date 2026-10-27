"""Graph quality metrics over the SQLite index.

The collector is read-only and deterministic: it reports the distribution of
symbols, edges, resolution tiers, unresolved targets, and coverage gaps for the
current index generation. It backs ``code-search stats`` and the graph-schema
surface so an agent can measure the graph before asking structural questions.
"""

from __future__ import annotations

from typing import Any

from code_search.engine.graph import GraphDatabase

_UNRESOLVED_TOP_LIMIT = 20


def collect_graph_metrics(
    db: GraphDatabase, *, unresolved_limit: int = _UNRESOLVED_TOP_LIMIT
) -> dict[str, Any]:
    """Return symbol, edge, and coverage metrics for the current index.

    Args:
        db: The graph database to inspect.
        unresolved_limit: Maximum unresolved raw targets to report (clipped to
            100) in the ``unresolved_top`` list.

    Returns:
        A JSON-serialisable dict with ``index_generation``, the graph-semantic
        ``index_format_version``, edge totals and per-type/tier breakdowns, the
        most frequent unresolved targets, symbol counts by kind and language,
        entry points by reason, importance availability, and coverage rows
        grouped by kind.
    """
    unresolved_limit = max(1, min(unresolved_limit, 100))
    with db.connect() as conn:
        generation_row = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_generation';"
        ).fetchone()
        generation = generation_row["value"] if generation_row is not None else None

        by_type: dict[str, dict[str, int]] = {}
        for row in conn.execute(
            "SELECT edge_type, COUNT(*) AS total, COALESCE(SUM(resolved), 0) AS resolved "
            "FROM graph_edges GROUP BY edge_type ORDER BY edge_type;"
        ):
            total = int(row["total"])
            resolved = int(row["resolved"])
            by_type[str(row["edge_type"])] = {
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
            }

        by_tier: dict[str, int] = {}
        for row in conn.execute(
            "SELECT COALESCE(resolution_tier, 'none') AS tier, COUNT(*) AS total "
            "FROM graph_edges GROUP BY COALESCE(resolution_tier, 'none') ORDER BY tier;"
        ):
            by_tier[str(row["tier"])] = int(row["total"])

        unresolved_top = [
            {"target_raw": row["target_raw"], "count": int(row["total"])}
            for row in conn.execute(
                "SELECT COALESCE(target_raw, '') AS target_raw, COUNT(*) AS total "
                "FROM graph_edges WHERE resolved = 0 "
                "GROUP BY COALESCE(target_raw, '') "
                "ORDER BY total DESC, target_raw ASC LIMIT ?;",
                (unresolved_limit,),
            )
            if row["target_raw"]
        ]

        symbols_by_kind = {
            str(row["kind"]): int(row["total"])
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS total FROM symbols GROUP BY kind ORDER BY kind;"
            )
        }
        symbols_by_language = {
            str(row["language"]): int(row["total"])
            for row in conn.execute(
                "SELECT language, COUNT(*) AS total FROM symbols "
                "GROUP BY language ORDER BY language;"
            )
        }

        coverage_by_kind: dict[str, int] = {}
        coverage_params: tuple[Any, ...] = ()
        coverage_sql = "SELECT kind, COUNT(*) AS total FROM index_coverage"
        if generation is not None:
            coverage_sql += " WHERE generation = ?"
            coverage_params = (generation,)
        coverage_sql += " GROUP BY kind ORDER BY kind;"
        for row in conn.execute(coverage_sql, coverage_params):
            coverage_by_kind[str(row["kind"])] = int(row["total"])

        entry_points_by_reason = {
            str(row["reason"]): int(row["total"])
            for row in conn.execute(
                "SELECT COALESCE(entry_point_reason, 'unknown') AS reason, "
                "COUNT(*) AS total FROM symbols WHERE is_entry_point = 1 "
                "GROUP BY COALESCE(entry_point_reason, 'unknown') ORDER BY reason;"
            )
        }
        format_row = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_format_version';"
        ).fetchone()
        index_format_version = (
            int(format_row["value"]) if format_row is not None and format_row["value"] else None
        )
        importance_row = conn.execute(
            "SELECT COUNT(*) AS nonzero, COALESCE(MAX(importance), 0) AS maximum "
            "FROM symbols WHERE importance > 0;"
        ).fetchone()

    totals: dict[str, Any] = {
        "total": sum(stat["total"] for stat in by_type.values()),
        "resolved": sum(stat["resolved"] for stat in by_type.values()),
        "unresolved": sum(stat["unresolved"] for stat in by_type.values()),
    }
    totals["resolution_ratio"] = (
        round(totals["resolved"] / totals["total"], 4) if totals["total"] else 0.0
    )
    importance_max = (
        round(float(importance_row["maximum"]), 6) if importance_row is not None else 0.0
    )
    importance_nonzero = int(importance_row["nonzero"]) if importance_row is not None else 0
    return {
        "index_generation": generation,
        "index_format_version": index_format_version,
        "edges": {"by_type": by_type, "by_tier": by_tier, **totals},
        "unresolved_top": unresolved_top,
        "symbols": {
            "total": sum(symbols_by_kind.values()),
            "by_kind": symbols_by_kind,
            "by_language": symbols_by_language,
        },
        "entry_points": {
            "total": sum(entry_points_by_reason.values()),
            "by_reason": entry_points_by_reason,
        },
        "importance": {
            "available": index_format_version is not None,
            "nonzero": importance_nonzero,
            "max": importance_max,
        },
        "coverage": {
            "generation": generation,
            "total": sum(coverage_by_kind.values()),
            "by_kind": coverage_by_kind,
            # A clean index has no recorded gaps; absence of a gap is still not
            # proof of completeness, but a recorded gap is proof of a gap.
            "complete": sum(coverage_by_kind.values()) == 0,
        },
    }
