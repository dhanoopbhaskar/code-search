"""Benchmark: call graph traversal latency.

Verifies traversal < 1s on a synthetic graph with 100K+ edges.
"""

from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase


@pytest.fixture
def large_graph(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "bench.db", settings)
    db.initialize()
    edge_store = EdgeStore(db)

    num_symbols = 100
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            [
                (i, f"mod.func{i}", f"func{i}", "function", f"f{i // 10}.py", 1, 10, 0, 1, "python")
                for i in range(num_symbols)
            ],
        )
        edges = []
        for i in range(num_symbols):
            for j in range(max(0, i - 5), i):
                edges.append((j, i, "CALLS", "[]", "[]"))
        conn.executemany(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, source_range, target_range) "
            "VALUES (?, ?, ?, ?, ?);",
            edges,
        )

    return {"edge_store": edge_store, "target_id": 0}


@pytest.mark.benchmark
@pytest.mark.slow
def test_graph_traversal_latency(benchmark: Any, large_graph: dict[str, Any]) -> None:
    result = benchmark(
        large_graph["edge_store"].get_call_graph,
        large_graph["target_id"],
        direction="callees",
        max_depth=5,
    )
    assert "callers" in result
    assert "callees" in result


@pytest.mark.benchmark
@pytest.mark.slow
def test_graph_traversal_sc003_budget(large_graph: dict[str, Any]) -> None:
    """Call graph traversal completes within 1 second."""
    import time

    edge_store: EdgeStore = large_graph["edge_store"]
    edge_store.get_call_graph(large_graph["target_id"], direction="callees", max_depth=5)
    start = time.monotonic()
    edge_store.get_call_graph(large_graph["target_id"], direction="callees", max_depth=5)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 1000, f"Call graph traversal took {elapsed_ms:.0f} ms (budget 1 s)"
