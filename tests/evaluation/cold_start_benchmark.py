#!/usr/bin/env python3
"""Repeatable cold-start latency benchmark on a fixed corpus.

Measures the first-query (reduced cold path) and steady-state (warm) ranked
latency percentiles, counts model loads, and reports a ``pass``/``fail`` verdict
against the interactive cold ceiling and the recorded warm baseline. All
measurement is CPU-only with zero outbound connections.

Run standalone with::

    python -m tests.evaluation.cold_start_benchmark --runs 30
    python -m tests.evaluation.cold_start_benchmark --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import FIXTURES_DIR, _indexed_components

DEFAULT_FIXTURE = "relevance"
DEFAULT_RUNS = 30
DEFAULT_LIMIT = 5
QUERY = "how do comments get created"

#: The interactive first-query ceiling: the reduced cold path must return
#: under this on CPU-only hardware for every entry point.
COLD_BUDGET_MS = 200.0

#: Recorded pre-change warm-latency baseline on the fixed corpus. The
#: measured warm p99 before this feature was ~8 ms; the threshold includes
#: margin for normal CI variance so the gate catches real regressions without
#: flapping.
WARM_BASELINE_MS = 100.0


def _percentiles(values: list[float]) -> tuple[float, float]:
    """Return the p50 and p99 of *values* (milliseconds)."""
    ordered = sorted(values)
    p50 = statistics.median(ordered)
    p99 = ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))]
    return p50, p99


def _counted_loader() -> tuple[Any, dict[str, int]]:
    """Wrap ``_load_model`` to count real model loads.

    A load is counted only when the module singleton transitions from absent to
    present, so repeated calls that reuse a cached model are not double-counted.
    """
    from src.engine import embeddings

    original = embeddings._load_model
    state = {"loads": 0}

    def wrapper(settings: Any = None) -> Any:
        before = embeddings._model_instance
        result = original(settings)
        after = embeddings._model_instance
        if before is None and after is not None and after is not embeddings._LOAD_FAILED_SENTINEL:
            state["loads"] += 1
        return result

    embeddings._load_model = wrapper
    return original, state


def run_benchmark(
    work_dir: Path,
    runs: int = DEFAULT_RUNS,
    limit: int = DEFAULT_LIMIT,
    corpus: str = DEFAULT_FIXTURE,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Run the cold/warm latency benchmark and return the report.

    Args:
        work_dir: Scratch directory for the fixture and its index.
        runs: Number of cold and warm repetitions.
        limit: Results per query.
        corpus: Corpus label echoed into the report.
        repo: Optional external repo to index instead of the hermetic fixture.

    Returns:
        The benchmark report with cold/warm percentiles, ``load_count``, a
        representative latency breakdown, and a ``pass``/``fail`` verdict.
    """
    from src.engine import embeddings
    from src.engine.embeddings import EmbeddingGenerator
    from src.engine.search import HybridSearch

    original_load, load_state = _counted_loader()
    # Force a genuinely cold module singleton so the count measures the loads
    # this benchmark triggers, not a model another test already loaded. The
    # singleton is restored in the ``finally`` block below.
    saved_instance = embeddings._model_instance
    saved_path = embeddings._loaded_model_path
    embeddings._model_instance = None
    embeddings._loaded_model_path = None
    try:
        if repo is not None:
            repo_path = repo.resolve()
            context_dir = repo_path / ".context"
        else:
            repo_path = work_dir / "relevance_repo"
            shutil.copytree(FIXTURES_DIR / DEFAULT_FIXTURE, repo_path)
            context_dir = repo_path / ".context"
        components = _indexed_components(
            repo_path, context_dir, settings_kwargs={"index_prose": True}
        )

        settings = components["settings"]
        # Controlled cold state: a generator that never starts an in-process
        # load, so the reduced path is measured deterministically.
        cold_gen = EmbeddingGenerator(settings)
        cold_gen.warmup_external = True
        cold_search = HybridSearch(components["db"], components["vector_index"], cold_gen, settings)

        cold_latencies: list[float] = []
        for _ in range(runs):
            cold_gen.reset_model()
            start = time.monotonic()
            envelope = cold_search.search(QUERY, limit=limit)
            cold_latencies.append((time.monotonic() - start) * 1000.0)
            if envelope.get("ranked_path") != "lexical_reduced":
                raise RuntimeError(
                    "cold benchmark query was not served from the reduced path: "
                    f"{envelope.get('ranked_path')!r}"
                )

        warm_search = components["search"]
        warm_search.search(QUERY, limit=limit)  # ensure warm
        warm_latencies: list[float] = []
        breakdown: dict[str, int] | None = None
        for _ in range(runs):
            start = time.monotonic()
            warm_envelope = warm_search.search(QUERY, limit=limit)
            warm_latencies.append((time.monotonic() - start) * 1000.0)
            status = warm_envelope.get("model_status")
            if isinstance(status, dict) and status.get("latency_breakdown"):
                breakdown = status["latency_breakdown"]

        cold_p50, cold_p99 = _percentiles(cold_latencies)
        warm_p50, warm_p99 = _percentiles(warm_latencies)
        load_count = load_state["loads"]

        verdict = (
            "pass"
            if cold_p99 < COLD_BUDGET_MS and warm_p99 <= WARM_BASELINE_MS and load_count == 1
            else "fail"
        )
        return {
            "corpus": corpus,
            "runs": runs,
            "cpu_only": True,
            "cold": {"p50_ms": cold_p50, "p99_ms": cold_p99, "budget_ms": COLD_BUDGET_MS},
            "warm": {"p50_ms": warm_p50, "p99_ms": warm_p99, "baseline_ms": WARM_BASELINE_MS},
            "load_count": load_count,
            "breakdown": breakdown,
            "verdict": verdict,
        }
    finally:
        embeddings._load_model = original_load
        embeddings._model_instance = saved_instance
        embeddings._loaded_model_path = saved_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: run the benchmark, print the report, and exit non-zero on failure."""
    parser = argparse.ArgumentParser(description="Cold-start latency benchmark")
    parser.add_argument("--repo", type=Path, default=None, help="External repo to index")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--output", type=Path, default=None, help="Write report JSON here")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="cold_start_bench_") as tmp:
        repo = args.repo.resolve() if args.repo else None
        corpus = str(repo) if repo else DEFAULT_FIXTURE
        report = run_benchmark(
            Path(tmp), runs=args.runs, limit=args.limit, corpus=corpus, repo=repo
        )

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    print(payload)
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
