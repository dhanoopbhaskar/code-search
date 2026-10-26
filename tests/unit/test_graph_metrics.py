"""Unit tests for the graph quality metrics collector."""

from __future__ import annotations

from pathlib import Path

from code_search.engine.config import Settings
from code_search.engine.graph import GraphDatabase
from code_search.engine.graph_metrics import collect_graph_metrics


def test_collect_graph_metrics_reports_edges_coverage_and_generation(tmp_path: Path) -> None:
    """Metrics summarise edge resolution, unresolved targets, and coverage."""
    db = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES ('/repo/a.py::caller', 'caller', 'function', '/repo/a.py', 0, 3, 0, 1, "
            "'python');"
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES ('/repo/a.py::callee', 'callee', 'function', '/repo/a.py', 5, 7, 0, 1, "
            "'python');"
        )
        source = conn.execute(
            "SELECT id FROM symbols WHERE fqn = '/repo/a.py::caller';"
        ).fetchone()["id"]
        target = conn.execute(
            "SELECT id FROM symbols WHERE fqn = '/repo/a.py::callee';"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (?, ?, 'CALLS', 'exact', 1);",
            (source, target),
        )
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved, target_raw) VALUES (?, NULL, 'CALLS', NULL, 0, "
            "'external.save');",
            (source,),
        )
        conn.execute(
            "INSERT INTO index_coverage (file_path, kind, detail, generation) "
            "VALUES ('/repo/a.py', 'parse_partial', '1 syntax error range(s)', 'gen-1');"
        )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_generation', 'gen-1');"
        )

    metrics = collect_graph_metrics(db)

    assert metrics["index_generation"] == "gen-1"
    assert metrics["edges"]["total"] == 2
    assert metrics["edges"]["resolved"] == 1
    assert metrics["edges"]["unresolved"] == 1
    assert metrics["edges"]["by_type"]["CALLS"]["total"] == 2
    assert metrics["unresolved_top"] == [{"target_raw": "external.save", "count": 1}]
    assert metrics["symbols"]["total"] == 2
    assert metrics["symbols"]["by_kind"] == {"function": 2}
    assert metrics["coverage"]["by_kind"] == {"parse_partial": 1}
    assert metrics["coverage"]["complete"] is False
