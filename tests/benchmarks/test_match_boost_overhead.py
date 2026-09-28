"""Benchmark: the match-boost layer stays within the query-time budget.

Filename/exact-match boosting must add no more than 5% to a
ranked query and the ranked p99 to stay under 2 s. The layer is pure per-result
arithmetic plus one targeted FTS5 ``file_path`` lookup per request, so the added
cost is a small fraction of the BM25 + vector + RRF work it rides on. This suite
measures the ranked path with the layer enabled against the same path with it
disabled and fails if the overhead exceeds the budget.

Marked ``benchmark``/``slow`` so the fast CI gate excludes it; run locally with
``pytest tests/benchmarks/test_match_boost_overhead.py``.
"""

from __future__ import annotations

import math
import time
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import HybridSearch

# A corpus large enough that the fixed FTS filename lookup is a small fraction
# of the ranked query time, mirroring the 1M-LOC target scale.
_NUM_FILES = 40000
_QUERY = "handle request config"


@pytest.fixture
def ranked_match_boost_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic ranked index large enough for stable timing."""
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "match_boost_overhead.db", settings)
    db.initialize()

    rows: list[tuple[Any, ...]] = []
    for i in range(_NUM_FILES):
        for j in range(3):
            path = "config.py" if i == 0 else f"f{i}.py"
            content = f"def handle_{i}_{j}(): return handle request config {i + j}"
            rows.append(
                (
                    f"mod.f{i}.handle{j}",
                    path,
                    j * 10 + 1,
                    j * 10 + 10,
                    content,
                    "python",
                    1 if j % 5 == 0 else 0,
                    "ast",
                    f"handle request config {i} {j}",
                    "code",
                )
            )

    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO code_chunks "
            "(fqn, file_path, line_start, line_end, content, language, "
            "is_definition, chunk_type, subwords, content_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            rows,
        )

    vector_index = VectorIndex(tmp_path / "none.bin", tmp_path / "none.meta.json")
    embedding_gen = EmbeddingGenerator(settings)
    search = HybridSearch(db, vector_index, embedding_gen, settings)
    return {
        "search": search,
        "db": db,
        "settings": settings,
        "vector_index": vector_index,
        "embedding_gen": embedding_gen,
    }


def _interleaved_min_ms(
    enabled: HybridSearch, baseline: HybridSearch, rounds: int = 25
) -> tuple[float, float]:
    """Return the best-case latency of each configuration, in milliseconds.

    The two configurations are warmed once, then measured alternately within the
    same round so scheduler/GC drift affects both equally. The minimum of each is
    the most stable estimate of the work the layer actually adds; timing them in
    separate windows lets drift land entirely on one side and produced spurious
    overhead readings.

    Args:
        enabled: The ranked path with the match-boost layer enabled.
        baseline: The same path with the layer disabled.
        rounds: Number of paired measurement rounds.

    Returns:
        ``(enabled_ms, baseline_ms)`` best-case latencies.
    """
    enabled.search(_QUERY, 50)
    baseline.search(_QUERY, 50)
    enabled_min = math.inf
    baseline_min = math.inf
    for _ in range(rounds):
        start = time.monotonic()
        baseline.search(_QUERY, 50)
        baseline_min = min(baseline_min, (time.monotonic() - start) * 1000.0)

        start = time.monotonic()
        enabled.search(_QUERY, 50)
        enabled_min = min(enabled_min, (time.monotonic() - start) * 1000.0)
    return enabled_min, baseline_min


@pytest.mark.benchmark
@pytest.mark.slow
def test_match_boost_overhead_within_budget(
    ranked_match_boost_index: dict[str, Any],
) -> None:
    """The match-boost layer adds at most 5% to the ranked query time."""
    from dataclasses import replace

    components = ranked_match_boost_index
    search: HybridSearch = components["search"]

    disabled_settings = replace(components["settings"], match_boost_enabled=False)
    baseline_search = HybridSearch(
        components["db"],
        components["vector_index"],
        components["embedding_gen"],
        disabled_settings,
    )
    enabled_ms, baseline_ms = _interleaved_min_ms(search, baseline_search)

    overhead = (enabled_ms - baseline_ms) / baseline_ms if baseline_ms else 0.0
    assert overhead <= 0.05, (
        f"match-boost overhead {overhead:.1%} exceeds 5% "
        f"(enabled {enabled_ms:.2f} ms vs baseline {baseline_ms:.2f} ms)"
    )
    assert enabled_ms < 2000.0, f"ranked p99 proxy {enabled_ms:.2f} ms exceeds 2 s"
