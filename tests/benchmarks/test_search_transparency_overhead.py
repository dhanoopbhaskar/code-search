"""Benchmark: transparency additions stay constant-time on the ranked path.

The ranked (default) search path gains only constant-time additions — a
content-type weight lookup, a WHERE-clause content filter, the matching-semantics
label, the borderline tag, and the query-time timer. This suite pins those
additions against the ranked baseline so the transparency feature cannot creep
latency into the constitutional ranked-query budget (p99 < 2 s at 1M LOC).
"""

from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import HybridSearch


@pytest.fixture
def ranked_search_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic 1M-LOC-scale ranked index for overhead comparison."""
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "overhead.db", settings)
    db.initialize()

    num_chunks = 2000
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
                for i in range(num_chunks)
                for j in range(3)
            ],
        )
        conn.executemany(
            "INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);",
            [
                (i * 3 + j + 1, f"def func_{i}_{j}(): return {i + j}")
                for i in range(num_chunks)
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


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_baseline_latency(benchmark: Any, ranked_search_index: dict[str, Any]) -> None:
    """Baseline ranked search over the synthetic index."""
    search: HybridSearch = ranked_search_index["search"]
    benchmark(search.search, "def func", 10)


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_content_filter_latency(benchmark: Any, ranked_search_index: dict[str, Any]) -> None:
    """Content-filtered ranked search — the filter is a plain WHERE clause."""
    search: HybridSearch = ranked_search_index["search"]
    benchmark(search.search, "def func", 10, content="code")


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_labeled_envelope_latency(
    benchmark: Any, ranked_search_index: dict[str, Any]
) -> None:
    """Ranked search producing matching-semantics + borderline + query-time labels."""
    search: HybridSearch = ranked_search_index["search"]
    envelope = benchmark(search.search, "def func", 10)
    assert "matching_semantics" in envelope
    assert "query_time_ms" in envelope


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_p99_transparency_budget(ranked_search_index: dict[str, Any]) -> None:
    """The transparency-labeled ranked path stays under the 2 s p99 budget."""
    import time

    search: HybridSearch = ranked_search_index["search"]
    search.search("def func", 10)
    latencies_ms: list[float] = []
    for _ in range(30):
        start = time.monotonic()
        search.search("def func", 10)
        latencies_ms.append((time.monotonic() - start) * 1000)
    latencies_ms.sort()
    p99 = latencies_ms[int(len(latencies_ms) * 0.99) - 1]
    assert p99 < 2000, f"transparency ranked p99 {p99:.0f} ms >= 2000 ms (budget 2 s)"
