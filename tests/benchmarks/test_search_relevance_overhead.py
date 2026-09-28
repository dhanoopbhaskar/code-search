"""Benchmark: relevance additions stay constant-time on the ranked path.

The ranked (default) search path gains only constant-time additions — the
docs-exclusion WHERE clause (the code-focused default scope), the ranked
relevance floor on the top fused score, the warm/cold model-status stamp, and
the per-request literal matching selection. This suite pins those additions
against the ranked baseline so the relevance feature cannot creep latency into
the constitutional ranked-query budget (p99 < 2 s at 1M LOC).
"""

from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import HybridSearch


@pytest.fixture
def relevance_search_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic ranked index with code + config + docs chunks."""
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "relevance_overhead.db", settings)
    db.initialize()

    num_chunks = 2000
    rows: list[tuple[Any, ...]] = []
    fts_rows: list[tuple[Any, ...]] = []
    idx = 0
    for i in range(num_chunks):
        for j in range(3):
            idx += 1
            rows.append(
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
            )
            fts_rows.append((idx, f"def func_{i}_{j}(): return {i + j}"))
    # A handful of docs/config chunks so the scoped and unfiltered paths both
    # exercise the content-type predicates.
    for k in range(20):
        idx += 1
        rows.append(
            (
                f"doc.d{k}",
                f"docs/note{k}.md",
                k + 1,
                k + 5,
                f"# notes on func {k}",
                "markdown",
                0,
                "raw_text",
                f"notes func {k}",
                "docs",
            )
        )
        fts_rows.append((idx, f"# notes on func {k}"))
    with db.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO code_chunks "
            "(fqn, file_path, line_start, line_end, content, language, "
            "is_definition, chunk_type, subwords, content_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            rows,
        )
        conn.executemany("INSERT INTO chunks_fts (rowid, content) VALUES (?, ?);", fts_rows)

    search = HybridSearch(
        db,
        VectorIndex(tmp_path / "none.bin", tmp_path / "none.meta.json"),
        EmbeddingGenerator(settings),
        settings,
    )
    return {"search": search, "db": db, "settings": settings}


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_baseline_latency(benchmark: Any, relevance_search_index: dict[str, Any]) -> None:
    """Baseline ranked search over the synthetic index."""
    search: HybridSearch = relevance_search_index["search"]
    benchmark(search.search, "def func", 10, content="all")


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_code_focused_default_latency(
    benchmark: Any, relevance_search_index: dict[str, Any]
) -> None:
    """Code-focused default scope — the docs-exclusion WHERE clause is a
    constant-time predicate over the existing content_type column."""
    search: HybridSearch = relevance_search_index["search"]
    envelope = benchmark(search.search, "def func", 10)
    assert envelope["content"] == "code_focused"
    assert all(r["content_type"] != "docs" for r in envelope["results"])


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_relevance_floor_latency(
    benchmark: Any, relevance_search_index: dict[str, Any]
) -> None:
    """A below-floor gibberish query routes through the relevance floor to the
    no-match envelope — a constant-time max over the fused scores."""
    search: HybridSearch = relevance_search_index["search"]
    envelope = benchmark(search.search, "florble waffle quux", 10)
    assert envelope.get("no_match") is True


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_model_status_latency(
    benchmark: Any, relevance_search_index: dict[str, Any]
) -> None:
    """The model-status stamp is a boolean read of existing model state."""
    search: HybridSearch = relevance_search_index["search"]
    envelope = benchmark(search.search, "def func", 10)
    assert "model_status" in envelope
    assert "query_time_ms" in envelope


@pytest.mark.benchmark
@pytest.mark.slow
def test_ranked_p99_relevance_budget(relevance_search_index: dict[str, Any]) -> None:
    """The relevance-labeled ranked path stays under the 2 s p99 budget."""
    import time

    search: HybridSearch = relevance_search_index["search"]
    search.search("def func", 10)
    latencies_ms: list[float] = []
    for _ in range(30):
        start = time.monotonic()
        search.search("def func", 10)
        latencies_ms.append((time.monotonic() - start) * 1000)
    latencies_ms.sort()
    p99 = latencies_ms[int(len(latencies_ms) * 0.99) - 1]
    assert p99 < 2000, f"relevance ranked p99 {p99:.0f} ms >= 2000 ms (budget 2 s)"


@pytest.mark.benchmark
@pytest.mark.slow
def test_exhaustive_matching_selection_latency(
    benchmark: Any, relevance_search_index: dict[str, Any]
) -> None:
    """Literal matching selection is a per-request argument to the existing
    exhaustive scan — no new cost profile."""
    search: HybridSearch = relevance_search_index["search"]
    envelope = benchmark(search.search, "func_12", 10, mode="exhaustive", matching="literal")
    assert envelope["matching_semantics"] == "literal"
