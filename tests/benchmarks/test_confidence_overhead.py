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

import math
import time
from typing import Any

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import GraphDatabase
from code_search.engine.search import HybridSearch


@pytest.fixture
def ranked_search_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic ranked index large enough for stable timing."""
    from code_search.engine.embeddings import EmbeddingGenerator, VectorIndex

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


def _interleaved_min_ms(
    search: HybridSearch, use_baseline: Any, rounds: int = 25
) -> tuple[float, float]:
    """Return best-case latency for each blend, in milliseconds.

    The two configurations are warmed once, then measured alternately within
    the same round so scheduler/GC drift affects both equally. The minimum of
    each is the most stable estimate of the work calibration actually adds;
    timing them in separate windows lets drift land entirely on one side and
    produced spurious overhead readings.

    Args:
        search: The ranked search under test.
        use_baseline: Mutable flag; set to ``True`` to select the base blend.
        rounds: Number of paired measurement rounds.

    Returns:
        ``(calibrated_ms, baseline_ms)`` best-case latencies.
    """
    search.search("def func", 10)
    calibrated_min = math.inf
    baseline_min = math.inf
    for _ in range(rounds):
        use_baseline[0] = True
        start = time.monotonic()
        search.search("def func", 10)
        baseline_min = min(baseline_min, (time.monotonic() - start) * 1000.0)

        use_baseline[0] = False
        start = time.monotonic()
        search.search("def func", 10)
        calibrated_min = min(calibrated_min, (time.monotonic() - start) * 1000.0)
    return calibrated_min, baseline_min


@pytest.mark.benchmark
@pytest.mark.slow
def test_confidence_overhead_within_budget(
    ranked_search_index: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calibration adds at most 5% over the base-blend ranked path."""
    import code_search.engine.confidence as confidence_module
    import code_search.engine.search as search_module

    search: HybridSearch = ranked_search_index["search"]
    use_baseline = [False]

    def _blend(evidence: Any, context: Any) -> float:
        if use_baseline[0]:
            return confidence_module.confidence_score(
                evidence.query_subwords, evidence.chunk_subwords, evidence.vector_score
            )
        return confidence_module.calibrated_confidence(evidence, context)

    monkeypatch.setattr(search_module, "calibrated_confidence", _blend)

    calibrated_ms, baseline_ms = _interleaved_min_ms(search, use_baseline)

    overhead = (calibrated_ms - baseline_ms) / baseline_ms if baseline_ms else 0.0
    assert overhead <= 0.05, (
        f"confidence overhead {overhead:.1%} exceeds 5% "
        f"(calibrated {calibrated_ms:.2f} ms vs baseline {baseline_ms:.2f} ms)"
    )
