"""Benchmark: partial-name definition lookups stay within the 500 ms budget.

Every definition lookup for a partial name must complete within
the existing symbol-definition budget (p99 under 500 ms on CPU-only hardware).
The candidate query is bounded (``LIMIT 100``) and ranking is O(k log k) over
the clipped list, so the added work is a small fraction of the storage lookup.
This suite builds a synthetic symbol corpus large enough for stable timing and
fails if the partial-name p99 exceeds the budget.

Marked ``benchmark``/``slow`` so the fast CI gate excludes it; run locally with
``pytest tests/benchmarks/test_symbol_resolution_overhead.py -m benchmark``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.implementations import find_implementations
from src.engine.symbols import SymbolStore

# A corpus large enough that the bounded candidate query dominates the ranking.
_NUM_SYMBOLS = 20000
_ROUNDS = 60
_P99_BUDGET_MS = 500.0

#: Partial references exercising the unique, parent-qualified, suffix, and
#: multi-match paths.
_QUERIES = (
    "ArticleService.save",
    "article.ArticleService.save",
    "delete",
    "save",
)


@pytest.fixture
def resolution_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic symbol corpus with one overloaded target and many fillers."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "resolution_overhead.db", settings)
    db.initialize()

    rows: list[tuple[Any, ...]] = [
        (
            "src/main/ArticleService.java::ArticleService",
            "ArticleService",
            "class",
            "src/main/ArticleService.java",
            1,
            40,
            0,
            5,
            "java",
            None,
        ),
        (
            "src/main/ArticleService.java::ArticleService.save(Article)",
            "save",
            "method",
            "src/main/ArticleService.java",
            10,
            14,
            4,
            40,
            "java",
            None,
        ),
        (
            "src/main/ArticleService.java::ArticleService.save(Article,boolean)",
            "save",
            "method",
            "src/main/ArticleService.java",
            16,
            22,
            4,
            40,
            "java",
            None,
        ),
        (
            "src/main/ArticleService.java::ArticleService.delete(long)",
            "delete",
            "method",
            "src/main/ArticleService.java",
            24,
            28,
            4,
            40,
            "java",
            None,
        ),
    ]
    for i in range(_NUM_SYMBOLS):
        rows.append(
            (
                f"src/gen/Gen{i}.java::Gen{i}.handle{i}(String)",
                f"handle{i}",
                "method",
                f"src/gen/Gen{i}.java",
                1,
                5,
                0,
                30,
                "java",
                None,
            )
        )
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(fqn, name, kind, file_path, line_start, line_end, column_start, column_end, "
            "language, declared_rules) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            rows,
        )
    return {"store": SymbolStore(db, settings)}


def _p99_ms(store: SymbolStore) -> float:
    """Return the p99 partial-name lookup latency in milliseconds."""
    for query in _QUERIES:  # warm up
        store.resolve_name(query)
    latencies: list[float] = []
    for _ in range(_ROUNDS):
        for query in _QUERIES:
            start = time.monotonic()
            store.resolve_name(query)
            latencies.append((time.monotonic() - start) * 1000.0)
    latencies.sort()
    index = max(0, round(0.99 * len(latencies)) - 1)
    return latencies[index]


@pytest.mark.benchmark
@pytest.mark.slow
def test_partial_name_resolution_within_budget(resolution_index: dict[str, Any]) -> None:
    """The partial-name definition lookup p99 stays under 500 ms."""
    p99 = _p99_ms(resolution_index["store"])
    assert p99 < _P99_BUDGET_MS, f"partial-name resolution p99 {p99:.2f} ms exceeds 500 ms"


#: Number of direct implementers in the synthetic implementation corpus.
_IMPL_COUNT = 2000


@pytest.fixture
def implementations_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic interface with many direct implementers + implementations."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "impl_overhead.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)

    rows: list[dict[str, Any]] = [
        {
            "fqn": "src/impl/I.java::I",
            "name": "I",
            "kind": "interface",
            "file_path": "src/impl/I.java",
            "line_start": 1,
            "line_end": 5,
            "column_start": 0,
            "column_end": 5,
            "language": "java",
            "parent_fqn": None,
        },
        {
            "fqn": "src/impl/I.java::I.run(String)",
            "name": "run",
            "kind": "method",
            "file_path": "src/impl/I.java",
            "line_start": 3,
            "line_end": 4,
            "column_start": 2,
            "column_end": 20,
            "language": "java",
            "parent_fqn": "src/impl/I.java::I",
        },
    ]
    for i in range(_IMPL_COUNT):
        rows.append(
            {
                "fqn": f"src/impl/Impl{i}.java::Impl{i}",
                "name": f"Impl{i}",
                "kind": "class",
                "file_path": f"src/impl/Impl{i}.java",
                "line_start": 1,
                "line_end": 6,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            }
        )
        rows.append(
            {
                "fqn": f"src/impl/Impl{i}.java::Impl{i}.run(String)",
                "name": "run",
                "kind": "method",
                "file_path": f"src/impl/Impl{i}.java",
                "line_start": 3,
                "line_end": 4,
                "column_start": 2,
                "column_end": 20,
                "language": "java",
                "parent_fqn": f"src/impl/Impl{i}.java::Impl{i}",
            }
        )
    ids = symbol_store.insert_symbols_batch(rows)
    edge_store.insert_edges_batch(
        [
            {
                "source_symbol_id": ids[f"src/impl/Impl{i}.java::Impl{i}"],
                "target_symbol_id": ids["src/impl/I.java::I"],
                "edge_type": "INHERITS",
            }
            for i in range(_IMPL_COUNT)
        ]
    )
    return {
        "symbol_store": symbol_store,
        "edge_store": edge_store,
        "fqn": "src/impl/I.java::I.run(String)",
    }


@pytest.mark.benchmark
@pytest.mark.slow
def test_implementations_lookup_within_budget(implementations_index: dict[str, Any]) -> None:
    """Implementation lookup resolves within the <500 ms symbol budget."""
    symbol_store = implementations_index["symbol_store"]
    edge_store = implementations_index["edge_store"]
    fqn = implementations_index["fqn"]
    result = find_implementations(symbol_store, edge_store, fqn)
    assert result["outcome"] == "resolved"
    assert len(result["implementations"]) == _IMPL_COUNT

    latencies: list[float] = []
    for _ in range(5):
        start = time.monotonic()
        find_implementations(symbol_store, edge_store, fqn)
        latencies.append((time.monotonic() - start) * 1000.0)
    p99 = sorted(latencies)[-1]
    assert p99 < _P99_BUDGET_MS, f"implementation lookup {p99:.2f} ms exceeds 500 ms"
