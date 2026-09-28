"""Real-latency cold-start benchmark.

Marked ``benchmark``/``slow`` so the fast CI gate excludes it; run as a CI step
(and locally with ``pytest tests/benchmarks/test_cold_start_latency.py -q``).
Measures the real cold/reduced and warm ranked latencies against the ceilings
with margin for CI variance and asserts exactly one model load.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.benchmark
@pytest.mark.slow
def test_cold_start_latency_within_budget(tmp_path: Path) -> None:
    """The cold/reduced and warm ranked latencies stay within their ceilings."""
    from tests.evaluation.cold_start_benchmark import (
        COLD_BUDGET_MS,
        WARM_BASELINE_MS,
        run_benchmark,
    )

    report = run_benchmark(tmp_path, runs=20)
    assert report["cold"]["p99_ms"] < COLD_BUDGET_MS, report
    assert report["warm"]["p99_ms"] <= WARM_BASELINE_MS, report
    assert report["load_count"] == 1, report
    assert report["verdict"] == "pass", report
