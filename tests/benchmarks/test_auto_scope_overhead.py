"""Benchmark: auto-scope inference adds no cost to neutral queries.

The neutral/default path must stay byte-identical to the pre-feature baseline:
classification is an O(query-token) scan, no extra search pass runs for neutral,
explicit-scope, or non-empty default results, and the default ranked-path
latency budget is unchanged. This suite pins the neutral-query result sets and
the ranked p99 against ``tests/evaluation/auto_scope_baseline.json``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import GraphDatabase
from src.engine.search import HybridSearch

BASELINE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "auto_scope_baseline.json"

# The baseline p99 is machine-dependent; the guard allows generous headroom so
# a busy CI host does not fail a functionally constant-time change.
_P99_TOLERANCE_FACTOR = 4.0
_P99_TOLERANCE_MS = 50.0


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _build_benchmark_index(root: Path) -> HybridSearch:
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex

    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(context_dir=root)
    db = GraphDatabase(root / "auto_scope_overhead.db", settings)
    db.initialize()
    rows: list[tuple[Any, ...]] = []
    fts_rows: list[tuple[Any, ...]] = []
    idx = 0
    for i in range(2000):
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
    return HybridSearch(
        db,
        VectorIndex(root / "none.bin", root / "none.meta.json"),
        EmbeddingGenerator(settings),
        settings,
    )


@pytest.fixture
def auto_scope_benchmark_index(tmp_path: Any) -> dict[str, Any]:
    """A synthetic ranked index mirroring the pre-feature baseline corpus."""
    return {"search": _build_benchmark_index(tmp_path)}


def _relative_paths(results: list[dict[str, Any]]) -> list[str]:
    return sorted({Path(r["file_path"]).as_posix() for r in results})


@pytest.mark.benchmark
@pytest.mark.slow
def test_neutral_query_result_sets_match_baseline(
    auto_scope_benchmark_index: dict[str, Any],
) -> None:
    """Neutral-query result sets are unchanged by intent inference."""
    baseline = _load_baseline()
    search: HybridSearch = auto_scope_benchmark_index["search"]
    for query, expected in baseline["benchmark_index"]["cases"].items():
        envelope = search.search(query, limit=10)
        assert envelope["content"] == expected["content"], query
        assert envelope["scope"]["origin"] == "default", query
        assert envelope["scope"]["signal"] is None, query
        assert _relative_paths(envelope["results"]) == expected["result_files"], query


@pytest.mark.benchmark
@pytest.mark.slow
def test_default_ranked_p99_matches_baseline(
    auto_scope_benchmark_index: dict[str, Any],
) -> None:
    """The default ranked-path p99 stays within the baseline budget."""
    baseline = _load_baseline()
    budget = (
        float(baseline["benchmark_index"]["p99_latency_ms"]) * _P99_TOLERANCE_FACTOR
        + _P99_TOLERANCE_MS
    )
    search: HybridSearch = auto_scope_benchmark_index["search"]
    search.search("def func", 10)
    latencies_ms: list[float] = []
    for _ in range(30):
        start = time.monotonic()
        search.search("def func", 10)
        latencies_ms.append((time.monotonic() - start) * 1000)
    latencies_ms.sort()
    p99 = latencies_ms[int(len(latencies_ms) * 0.99) - 1]
    assert p99 <= budget, f"auto-scope ranked p99 {p99:.1f} ms exceeds budget {budget:.1f} ms"


@pytest.mark.benchmark
@pytest.mark.slow
def test_relevance_fixture_neutral_result_sets_match_baseline(
    indexed_relevance: dict[str, Any],
) -> None:
    """The docs-exclusion neutral cases keep their pre-feature results."""
    baseline = _load_baseline()
    root = indexed_relevance["repo"]
    search: HybridSearch = indexed_relevance["search"]
    for query, expected in baseline["relevance_fixture"]["cases"].items():
        envelope = search.search(query, limit=10)
        assert envelope["content"] == expected["content"], query
        relative = sorted(
            str(Path(r["file_path"]).relative_to(root))
            if str(r["file_path"]).startswith(str(root))
            else Path(r["file_path"]).as_posix()
            for r in envelope["results"]
        )
        assert relative == expected["result_files"], query
