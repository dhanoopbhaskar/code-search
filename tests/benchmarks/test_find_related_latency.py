"""Latency benchmark test for find_related.

Enforces p99 < 2000ms.
"""

from __future__ import annotations

import json
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import _find_related_payload
from tests.conftest import FIXTURES_DIR, _indexed_components

_ANCHOR_REL_PATH = Path("src", "main", "java", "com", "example", "article", "ArticleService.java")


def _find_line_number(file_path: Path, target: str) -> int:
    """Find the line number containing target string in file."""
    content = file_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        if target in line:
            return i
    raise ValueError(f"Line with '{target}' not found in {file_path}")


@pytest.fixture
def benchmark_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over tests/fixtures/relevance/ for benchmarking."""
    repo = tmp_path / "relevance_repo"
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    return _indexed_components(repo, repo / ".context")


@pytest.mark.benchmark
@pytest.mark.slow
def test_find_related_latency_p99_under_2000ms(benchmark_comps: dict[str, Any]) -> None:
    """find_related query latency p99 < 2000ms."""
    comps = benchmark_comps
    anchor_file = comps["repo"] / _ANCHOR_REL_PATH
    line_num = _find_line_number(anchor_file, "createComment")

    # Warm-up runs
    for _ in range(3):
        json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))

    # Benchmark runs
    num_runs = 100
    latencies = []
    for _ in range(num_runs):
        start = time.monotonic()
        json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))
        latencies.append((time.monotonic() - start) * 1000)  # Convert to ms

    # Calculate statistics
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p90 = latencies[int(0.9 * len(latencies))]
    p95 = latencies[int(0.95 * len(latencies))]
    p99 = latencies[int(0.99 * len(latencies))]
    mean = statistics.mean(latencies)
    stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0

    print(f"\nfind_related Latency Benchmark ({num_runs} runs)")
    print(f"  Mean:   {mean:.2f}ms")
    print(f"  Stdev:  {stdev:.2f}ms")
    print(f"  p50:    {p50:.2f}ms")
    print(f"  p90:    {p90:.2f}ms")
    print(f"  p95:    {p95:.2f}ms")
    print(f"  p99:    {p99:.2f}ms")
    print(f"  Max:    {max(latencies):.2f}ms")

    # Assert p99 < 2000ms
    assert p99 < 2000, f"p99 latency {p99:.2f}ms exceeds 2000ms budget"


@pytest.mark.benchmark
@pytest.mark.slow
def test_find_related_latency_consistency(benchmark_comps: dict[str, Any]) -> None:
    """Verify latency is consistent across multiple queries."""
    comps = benchmark_comps
    anchor_file = comps["repo"] / _ANCHOR_REL_PATH
    line_num = _find_line_number(anchor_file, "createComment")

    # Warm-up
    for _ in range(3):
        json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))

    # Run 50 queries
    latencies = []
    for _ in range(50):
        start = time.monotonic()
        json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))
        latencies.append((time.monotonic() - start) * 1000)

    # Check that no single query exceeds 2000ms
    max_latency = max(latencies)
    assert max_latency < 2000, f"Single query latency {max_latency:.2f}ms exceeds 2000ms budget"

    # Check coefficient of variation (stdev/mean) is reasonable
    mean = statistics.mean(latencies)
    stdev = statistics.stdev(latencies)
    cv = stdev / mean if mean > 0 else 0
    assert cv < 1.0, (
        f"Latency coefficient of variation {cv:.2f} too high (unpredictable performance)"
    )


@pytest.mark.benchmark
@pytest.mark.slow
def test_find_related_latency_with_different_limits(benchmark_comps: dict[str, Any]) -> None:
    """Verify latency scales reasonably with limit parameter."""
    comps = benchmark_comps
    anchor_file = comps["repo"] / _ANCHOR_REL_PATH
    line_num = _find_line_number(anchor_file, "createComment")

    limits = [5, 10, 20, 50, 100]
    results = {}

    for limit in limits:
        # Warm-up
        for _ in range(2):
            json.loads(_find_related_payload(comps, str(anchor_file), line_num, limit))

        latencies = []
        for _ in range(20):
            start = time.monotonic()
            json.loads(_find_related_payload(comps, str(anchor_file), line_num, limit))
            latencies.append((time.monotonic() - start) * 1000)

        results[limit] = {
            "p50": sorted(latencies)[len(latencies) // 2],
            "p99": sorted(latencies)[int(0.99 * len(latencies))],
        }

    print("\nLatency by limit:")
    for limit, metrics in results.items():
        print(f"  limit={limit:3d}: p50={metrics['p50']:.2f}ms, p99={metrics['p99']:.2f}ms")

    # All limits should meet p99 budget
    for limit, metrics in results.items():
        assert metrics["p99"] < 2000, (
            f"limit={limit}: p99={metrics['p99']:.2f}ms exceeds 2000ms budget"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
