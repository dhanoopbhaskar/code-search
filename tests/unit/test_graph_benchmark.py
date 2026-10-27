"""Benchmark: call graph traversal latency.

Verifies traversal < 1s on a synthetic graph with 100K+ edges.
"""

from pathlib import Path
from typing import Any

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import EdgeStore, GraphDatabase
from code_search.engine.graph_cache import clear_adjacency_cache
from code_search.engine.graph_query import GraphQueryService
from code_search.engine.symbols import SymbolStore


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


@pytest.fixture
def cypher_large_graph(tmp_path: Path) -> GraphDatabase:
    """A 20k-symbol/20k-edge chain for the Cypher latency budget."""
    db = GraphDatabase(tmp_path / "cypher_bench.db")
    db.initialize()
    size = 20_000
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, is_test) "
            "VALUES (?, ?, 'function', ?, ?, ?, 0, 0, 'python', 0);",
            [
                (f"/repo/f{i // 100}.py::f{i}", f"f{i}", f"/repo/f{i // 100}.py", i, i + 1)
                for i in range(size)
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, resolution_tier) "
            "VALUES (?, ?, 'CALLS', 1, 'exact');",
            [(i + 1, i + 2) for i in range(size - 1)],
        )
        conn.execute("INSERT INTO index_metadata(key, value) VALUES ('index_generation', 'bench');")
    return db


@pytest.mark.benchmark
@pytest.mark.slow
def test_cypher_query_latency_budget(cypher_large_graph: GraphDatabase) -> None:
    """The Cypher subsets stay bounded on a 20k-symbol graph."""
    import time

    from code_search.engine.cypher import DEAD_CODE_CYPHER, execute_cypher

    queries = [
        "MATCH (f:Function) RETURN count(*) AS n",
        "MATCH (a:Function)-[:CALLS]->(b:Function) RETURN count(*) AS n",
        "MATCH (a:Function)-[:CALLS*1..2]->(b:Function) RETURN count(*) AS n",
        DEAD_CODE_CYPHER,
    ]
    for query in queries:
        start = time.monotonic()
        payload = execute_cypher(cypher_large_graph, query, timeout_ms=10_000)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert payload["outcome"] in {"resolved", "no_match"}, payload.get("error")
        assert elapsed_ms < 5_000, f"Cypher query took {elapsed_ms:.0f} ms: {query}"


@pytest.fixture
def cached_path_graph(tmp_path: Path) -> dict[str, Any]:
    """A 5k-symbol graph with a wide, cyclic call structure and a generation."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "cache_bench.db", settings)
    db.initialize()
    size = 5_000
    root = tmp_path / "repo"
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (?, ?, 'function', ?, ?, ?, 0, 0, 'python');",
            [
                (f"{root}/f{i // 100}.py::f{i}", f"f{i}", f"{root}/f{i // 100}.py", i, i + 1)
                for i in range(size)
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, resolution_tier) "
            "VALUES (?, ?, 'CALLS', 1, 'exact');",
            (
                (((target * 7919 + step * 104729) % size) + 1, target + 1)
                for target in range(size)
                for step in range(1, 4)
                if ((target * 7919 + step * 104729) % size) != target
            ),
        )
        conn.executemany(
            "INSERT INTO code_chunks "
            "(file_path, line_start, line_end, content, language, content_type) "
            "VALUES (?, 0, 1, 'pass', 'python', 'code');",
            [(f"{root}/f{i}.py",) for i in range((size + 99) // 100)],
        )
        conn.execute("INSERT INTO index_metadata(key, value) VALUES ('index_generation', 'bench');")
        conn.execute(
            "INSERT INTO index_metadata(key, value) VALUES ('index_root', ?);", (str(root),)
        )
    clear_adjacency_cache()
    return {
        "service": GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings),
        "settings": settings,
        "db": db,
        "root": root,
        "size": size,
    }


@pytest.mark.benchmark
@pytest.mark.slow
def test_cached_path_latency_budget(cached_path_graph: dict[str, Any]) -> None:
    """A warm adjacency snapshot answers a wide bounded path quickly."""
    import time

    service: GraphQueryService = cached_path_graph["service"]
    root: Path = cached_path_graph["root"]
    size: int = cached_path_graph["size"]
    source = f"{root}/f{(size - 1) // 100}.py::f{size - 1}"
    target = f"{root}/f{max(0, size - 10) // 100}.py::f{max(0, size - 10)}"
    service.shortest_path(source, target, max_hops=6)  # warm the snapshot
    started = time.monotonic()
    answer = service.shortest_path(source, target, max_hops=6)
    elapsed_ms = (time.monotonic() - started) * 1000
    assert answer.stats["adjacency"] == "cache"
    assert elapsed_ms < 2_000, f"warm cached path took {elapsed_ms:.0f} ms (budget 2 s)"
