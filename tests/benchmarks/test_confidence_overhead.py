"""Benchmark: calibrated confidence stays within the query-time budget.

The confidence computation must add no more than 5% to a ranked
query. Calibration is pure per-result arithmetic (sub-word overlap, string
comparisons, one regex) with no extra DB access, so the added cost is a small
fraction of the BM25 + vector + RRF work it rides on. This suite measures the
ranked path with calibration against the same path using only the base blend
and fails if the overhead exceeds the 5% budget.

Marked ``benchmark``/``slow`` so the fast CI gate excludes it; run locally with
``pytest tests/benchmarks/test_confidence_overhead.py --benchmark-only``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import HybridSearch


@pytest.fixture
def ranked_search_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic ranked index large enough for stable timing."""
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "confidence_overhead.db", settings)
    db.initialize()

    num_files = 2000
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO code_chunks "
            "(fqn, file_path, line_start, line_end, content, language, "
            "is_definition, chunk_type, subwords, content_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            [
                (
                    f"mod.f{i}.func{j}",
                    f"f{i}.py",
                    j * 10 + 1,
                    j * 10 + 10,
                    f"def func_{i}_{j}(): return {i + j}",
                    "python",
                    1 if j % 5 == 0 else 0,
                    "ast",
                    f"func {i} {j}",
                    "code",
                )
                for i in range(num_files)
                for j in range(3)
            ],
        )
        conn.executemany(
            "INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);",
            [
                (i * 3 + j + 1, f"def func_{i}_{j}(): return {i + j}")
                for i in range(num_files)
                for j in range(3)
            ],
        )

    search = HybridSearch(
        db,
        VectorIndex(tmp_path / "none.bin", tmp_path / "none.meta.json"),
        EmbeddingGenerator(settings),
        settings,
    )
    return {"search": search, "db": db, "settings": settings}


def _median_ms(search: HybridSearch, rounds: int = 25) -> float:
    """Return the median ranked-query latency in milliseconds."""
    search.search("def func", 10)
    latencies: list[float] = []
    for _ in range(rounds):
        start = time.monotonic()
        search.search("def func", 10)
        latencies.append((time.monotonic() - start) * 1000.0)
    latencies.sort()
    return latencies[len(latencies) // 2]


@pytest.mark.benchmark
@pytest.mark.slow
def test_confidence_overhead_within_budget(
    benchmark: Any, ranked_search_index: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calibration adds at most 5% over the base-blend ranked path."""
    import src.engine.confidence as confidence_module
    import src.engine.search as search_module

    search: HybridSearch = ranked_search_index["search"]

    def _base_blend(evidence: Any, context: Any) -> float:
        return confidence_module.confidence_score(
            evidence.query_subwords, evidence.chunk_subwords, evidence.vector_score
        )

    monkeypatch.setattr(search_module, "calibrated_confidence", _base_blend)
    baseline_ms = _median_ms(search)
    monkeypatch.undo()

    benchmark.pedantic(lambda: search.search("def func", 10), rounds=25, iterations=1)
    calibrated_ms = float(benchmark.stats["median"]) * 1000.0

    overhead = (calibrated_ms - baseline_ms) / baseline_ms if baseline_ms else 0.0
    assert overhead <= 0.05, (
        f"confidence overhead {overhead:.1%} exceeds 5% "
        f"(calibrated {calibrated_ms:.2f} ms vs baseline {baseline_ms:.2f} ms)"
    )
