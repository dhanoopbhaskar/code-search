#!/usr/bin/env python3
"""Latency/quality tradeoff harness for the opt-in fast embedding profile.

Measures, per profile (``default`` and ``fast``), the model cold-load time,
first-query latency, steady-state warm-query latency, and retrieval accuracy
(P@5, MRR@10) on the existing labelled retrieval set. The ``fast`` profile is
reported as shipping only when it reduces cold-load time by at least 40 %
relative to the default while keeping accuracy within a 5 % relative delta.
The result is recorded even when no candidate qualifies, so the
profile is withheld rather than shipping a quality-collapsing option.

Run standalone with::

    python -m tests.evaluation.model_tradeoff_eval
    python -m tests.evaluation.model_tradeoff_eval --repo /path/to/repo
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
from tests.evaluation.ranking_eval import _compute_metrics
from tests.evaluation.ranking_ground_truth import GROUND_TRUTH_CASES

DEFAULT_FIXTURE = "relevance"
DEFAULT_LIMIT = 10
DEFAULT_RUNS = 10

#: Floors for shipping the fast profile: it must reduce cold-load time by at
#: least this fraction while staying within this relative accuracy delta of the
#: default.
FAST_LOAD_REDUCTION_FLOOR = 0.40
FAST_ACCURACY_DELTA_FLOOR = 0.05

_WARMUP_QUERIES = (
    "how do comments get created",
    "article pagination and filtering",
    "where is the JWT token generated",
)


def _measure_cold_load_ms(settings: Any) -> float | None:
    """Return the model cold-load time in ms, or ``None`` when unavailable."""
    from src.engine import embeddings
    from src.engine.embeddings import EmbeddingGenerator

    saved = embeddings._model_instance
    embeddings._model_instance = None
    try:
        gen = EmbeddingGenerator(settings)
        start = time.monotonic()
        gen.begin_warmup()
        if not gen.wait_warm(60.0):
            return None
        return (time.monotonic() - start) * 1000.0
    finally:
        embeddings._model_instance = saved


def evaluate_profile(
    profile: str,
    work_dir: Path,
    runs: int = DEFAULT_RUNS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Measure latency and accuracy for one model profile.

    Args:
        profile: The profile name (``default`` or ``fast``).
        work_dir: Scratch directory for the copied fixture and its index.
        runs: Warm-query repetitions for the latency percentiles.
        limit: Results per query for the accuracy metrics.

    Returns:
        A JSON-serializable result dict; ``available`` is ``False`` when the
        profile's local model is absent, in which case timings are ``None``.
    """
    from src.engine.config import Settings
    from src.engine.embeddings import profile_model_available

    repo = work_dir / f"{profile}_repo"
    if not repo.exists():
        shutil.copytree(FIXTURES_DIR / DEFAULT_FIXTURE, repo)
    context_dir = work_dir / f"{profile}_ctx"
    settings = Settings(context_dir=context_dir, model_profile=profile, index_prose=True)
    model, dim = settings.resolve_embedding_profile()

    result: dict[str, Any] = {
        "profile": profile,
        "embedding_model": model,
        "embedding_dim": dim,
        "available": False,
        "cold_load_ms": None,
        "first_query_ms": None,
        "warm_p50_ms": None,
        "warm_p99_ms": None,
        "precision_at_5": None,
        "mrr_at_10": None,
    }
    if not profile_model_available(settings):
        return result

    result["available"] = True
    result["cold_load_ms"] = _measure_cold_load_ms(settings)

    components = _indexed_components(repo, context_dir, settings_kwargs={"model_profile": profile})
    search = components["search"]
    search.search(_WARMUP_QUERIES[0], limit=limit)

    first_start = time.monotonic()
    search.search(_WARMUP_QUERIES[0], limit=limit)
    result["first_query_ms"] = (time.monotonic() - first_start) * 1000.0

    warm_latencies: list[float] = []
    for index in range(runs):
        query = _WARMUP_QUERIES[index % len(_WARMUP_QUERIES)]
        start = time.monotonic()
        search.search(query, limit=limit)
        warm_latencies.append((time.monotonic() - start) * 1000.0)
    warm_latencies.sort()
    result["warm_p50_ms"] = statistics.median(warm_latencies)
    p99_index = min(len(warm_latencies) - 1, int(0.99 * len(warm_latencies)))
    result["warm_p99_ms"] = warm_latencies[p99_index]

    metrics, _failures = _compute_metrics(search, GROUND_TRUTH_CASES, limit)
    result["precision_at_5"] = metrics.precision_at_5
    result["mrr_at_10"] = metrics.mrr_at_10
    return result


def _relative_delta(value: float | None, baseline: float | None) -> float | None:
    """Return the relative delta of *value* from *baseline*, or ``None``."""
    if value is None or baseline is None or baseline == 0:
        return None
    return abs(value - baseline) / baseline


def evaluate(
    work_dir: Path,
    runs: int = DEFAULT_RUNS,
    limit: int = DEFAULT_LIMIT,
    corpus: str = DEFAULT_FIXTURE,
) -> dict[str, Any]:
    """Evaluate both profiles and decide whether the fast profile qualifies.

    Returns:
        The tradeoff report: per-profile measurements, the fast profile's
        load reduction and accuracy delta, the shipping floors, and whether the
        fast profile qualifies to ship.
    """
    profiles = {
        name: evaluate_profile(name, work_dir, runs=runs, limit=limit)
        for name in ("default", "fast")
    }
    default = profiles["default"]
    fast = profiles["fast"]

    reduction: float | None = None
    if fast["cold_load_ms"] is not None and default["cold_load_ms"]:
        reduction = 1.0 - fast["cold_load_ms"] / default["cold_load_ms"]
    accuracy_delta: float | None = None
    if fast["available"]:
        deltas = [
            _relative_delta(fast["precision_at_5"], default["precision_at_5"]),
            _relative_delta(fast["mrr_at_10"], default["mrr_at_10"]),
        ]
        present = [d for d in deltas if d is not None]
        accuracy_delta = max(present) if present else None

    qualifies = bool(
        fast["available"]
        and reduction is not None
        and reduction >= FAST_LOAD_REDUCTION_FLOOR
        and accuracy_delta is not None
        and accuracy_delta <= FAST_ACCURACY_DELTA_FLOOR
    )
    return {
        "corpus": corpus,
        "runs": runs,
        "profiles": profiles,
        "fast_load_reduction": reduction,
        "fast_accuracy_delta": accuracy_delta,
        "fast_qualifies": qualifies,
        "floors": {
            "load_reduction": FAST_LOAD_REDUCTION_FLOOR,
            "accuracy_delta": FAST_ACCURACY_DELTA_FLOOR,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: evaluate both profiles and print the report."""
    parser = argparse.ArgumentParser(description="Fast-model latency/quality tradeoff")
    parser.add_argument("--repo", type=Path, default=None, help="External repo to index")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--output", type=Path, default=None, help="Write report JSON here")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="model_tradeoff_") as tmp:
        corpus = str(args.repo.resolve()) if args.repo else DEFAULT_FIXTURE
        report = evaluate(Path(tmp), runs=args.runs, limit=args.limit, corpus=corpus)

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
