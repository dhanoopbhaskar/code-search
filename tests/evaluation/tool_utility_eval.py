#!/usr/bin/env python3
"""Repeatable cold/warm utility harness for the external evaluation corpus.

Runs the eleven labelled tasks from the code-search utility report (plus an
adversarial abstention set) against a local repository, once through the
one-shot cold path and once through a warm daemon. Every run records the rank,
hit@1/3/5/10, latency, output bytes, ``ranked_path``, ``model_status``,
``warmup_state``, scope, and engine ``query_time_ms`` to JSONL so results can be
compared across commits.

The harness never downloads anything and never requires the corpus in CI: when
``--repo`` is absent and no default checkout exists it prints a skip notice and
exits successfully.

Run standalone with::

    python tests/evaluation/tool_utility_eval.py \
        --repo ~/git/baeldung-tutorials --json-out /tmp/utility.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.evaluation.tool_utility_ground_truth import (
    CaseScore,
    UtilityCase,
    cases,
    hit_rank,
)

DEFAULT_CORPUS_CANDIDATES = (
    Path.home() / "git" / "baeldung-tutorials",
    Path("/media/dhanoopbhaskar/hdd01/home/git/baeldung-tutorials"),
)
DEFAULT_LIMIT = 10
DEFAULT_TIMEOUT_S = 400.0


def _cli_command() -> list[str]:
    """Return the command prefix that runs the installed CLI module."""
    return [sys.executable, "-m", "code_search.cli.main"]


def _default_repo(explicit: str | None) -> Path | None:
    """Resolve the evaluation repository, or ``None`` when unavailable."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.is_dir() else None
    env = os.environ.get("CODE_SEARCH_EVAL_REPO")
    if env:
        path = Path(env).expanduser().resolve()
        return path if path.is_dir() else None
    for candidate in DEFAULT_CORPUS_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def _run(
    args: list[str],
    timeout: float = DEFAULT_TIMEOUT_S,
    stderr: int | None = subprocess.PIPE,
) -> tuple[float, int, str, str]:
    """Run *args* and return ``(elapsed_ms, returncode, stdout, stderr)``."""
    start = time.monotonic()
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        stderr=stderr,
    )
    elapsed_ms = (time.monotonic() - start) * 1000.0
    return elapsed_ms, proc.returncode, proc.stdout, proc.stderr or ""


def _index_if_needed(repo: Path, context_dir: Path) -> None:
    """Build the index when the context directory has no graph database."""
    if (context_dir / "graph.db").is_file():
        return
    print(f"Indexing {repo} (first run; this can take a while)...", file=sys.stderr)
    args = [*_cli_command(), "--context-dir", str(context_dir), "index", "--path", str(repo)]
    elapsed_ms, rc, _out, err = _run(args, timeout=4 * DEFAULT_TIMEOUT_S)
    print(f"Index finished in {elapsed_ms / 1000:.1f}s (rc={rc})", file=sys.stderr)
    if rc != 0:
        raise RuntimeError(f"index failed: {err[-2000:]}")


def _search_args(
    case: UtilityCase,
    context_dir: Path,
    limit: int,
    cold: bool,
) -> list[str]:
    """Build the CLI invocation for one case."""
    args = [
        *_cli_command(),
        "--context-dir",
        str(context_dir),
        "search",
        case.query,
        "--limit",
        str(limit),
        "--json",
        "--compact",
    ]
    if case.content_scope:
        args.extend(["--content", case.content_scope])
    if cold:
        args.append("--no-startup-check")
    return args


def _parse_envelope(stdout: str) -> tuple[list[str], dict[str, Any]]:
    """Return ``(ordered_paths, envelope)`` from a compact JSON response."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return [], {}
    results = data.get("results") or []
    paths = [str(item.get("file_path") or "") for item in results if item.get("file_path")]
    return paths, data


def _score(
    case: UtilityCase,
    mode: str,
    elapsed_ms: float,
    output_bytes: int,
    stdout: str,
    rc: int,
    error: str | None,
) -> CaseScore:
    """Score one invocation against its labelled expectations."""
    paths, envelope = _parse_envelope(stdout)
    no_match = envelope.get("no_match")
    abstained = bool(no_match) or (rc == 0 and not paths)
    rank = hit_rank(paths, case.expected_files) if case.expected_files else None
    scope = envelope.get("scope") or {}
    status = envelope.get("model_status")
    if isinstance(status, dict):
        status = status.get("state") or status.get("status")
    correct = abstained if case.expect_abstain else rank is not None
    return CaseScore(
        case_id=case.id,
        kind=case.kind,
        rank=rank,
        hit_at_1=rank == 1,
        hit_at_3=rank is not None and rank <= 3,
        hit_at_5=rank is not None and rank <= 5,
        hit_at_10=rank is not None and rank <= 10,
        abstained=abstained,
        correct=correct,
        latency_ms=round(elapsed_ms, 1),
        output_bytes=output_bytes,
        ranked_path=envelope.get("ranked_path"),
        model_status=str(status) if status is not None else None,
        warmup_state=envelope.get("warmup_state"),
        scope=scope.get("effective") if isinstance(scope, dict) else None,
        query_time_ms=envelope.get("query_time_ms"),
        mode=mode,
        error=error,
        extra={
            "paths": paths,
            "no_match_reason": (no_match or {}).get("reason")
            if isinstance(no_match, dict)
            else None,
        },
    )


def _run_case(case: UtilityCase, context_dir: Path, limit: int, cold: bool) -> CaseScore:
    """Run one case and return its score record."""
    args = _search_args(case, context_dir, limit, cold)
    try:
        elapsed_ms, rc, stdout, err = _run(args)
    except subprocess.TimeoutExpired:
        return CaseScore(
            case_id=case.id,
            kind=case.kind,
            rank=None,
            hit_at_1=False,
            hit_at_3=False,
            hit_at_5=False,
            hit_at_10=False,
            abstained=False,
            correct=False,
            latency_ms=round(DEFAULT_TIMEOUT_S * 1000, 1),
            output_bytes=0,
            mode="cold" if cold else "warm",
            error="timeout",
        )
    return _score(
        case,
        "cold" if cold else "warm",
        elapsed_ms,
        len(stdout.encode("utf-8")),
        stdout,
        rc,
        None if rc == 0 else err[-500:],
    )


def _warmup_cases(cases_to_run: tuple[UtilityCase, ...], context_dir: Path) -> None:
    """Start the daemon with the first case so the measured pass is warm."""
    if not cases_to_run:
        return
    args = _search_args(cases_to_run[0], context_dir, 1, cold=False)
    with contextlib.suppress(subprocess.TimeoutExpired):
        _run(args)


def run_evaluation(
    repo: Path | None,
    context_dir: Path | None,
    limit: int = DEFAULT_LIMIT,
    run_cold: bool = True,
    run_warm: bool = True,
    json_out: Path | None = None,
    include_adversarial: bool = True,
) -> dict[str, Any]:
    """Run the harness and return the aggregate report.

    Args:
        repo: Repository to index/search, or ``None`` to skip.
        context_dir: Explicit context directory; defaults to ``repo/.context``.
        limit: Results requested per query.
        run_cold: Whether to run the one-shot cold pass.
        run_warm: Whether to run the warm-daemon pass.
        json_out: JSONL output path; defaults to ``tool_utility_results.jsonl``.
        include_adversarial: Whether to include the adversarial negative set.

    Returns:
        A summary dict with per-mode aggregates and the per-case records.
    """
    if repo is None:
        return {"skipped": True, "reason": "evaluation corpus not found"}

    context = context_dir or (repo / ".context")
    _index_if_needed(repo, context)
    cases_to_run = cases(include_adversarial=include_adversarial)

    if run_warm:
        _warmup_cases(cases_to_run, context)

    records: list[CaseScore] = []
    if run_cold:
        for case in cases_to_run:
            records.append(_run_case(case, context, limit, cold=True))
    if run_warm:
        for case in cases_to_run:
            records.append(_run_case(case, context, limit, cold=False))

    destination = json_out or (Path.cwd() / "tool_utility_results.jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")

    return {
        "skipped": False,
        "repo": str(repo),
        "context_dir": str(context),
        "json_out": str(destination),
        "records": [record.as_dict() for record in records],
        "summary": _summarize(records),
    }


def _summarize(records: list[CaseScore]) -> dict[str, dict[str, float]]:
    """Aggregate hit rates and latency per mode."""
    summary: dict[str, dict[str, float]] = {}
    for mode in ("cold", "warm"):
        subset = [record for record in records if record.mode == mode]
        if not subset:
            continue
        positives = [record for record in subset if record.kind != "negative"]
        negatives = [record for record in subset if record.kind == "negative"]
        hits = [record for record in positives if record.hit_at_10]
        summary[mode] = {
            "queries": float(len(subset)),
            "hit_at_1": _rate(positives, lambda r: r.hit_at_1),
            "hit_at_3": _rate(positives, lambda r: r.hit_at_3),
            "hit_at_5": _rate(positives, lambda r: r.hit_at_5),
            "hit_at_10": _rate(positives, lambda r: r.hit_at_10),
            "abstention": _rate(negatives, lambda r: r.abstained) if negatives else 0.0,
            "median_latency_ms": _median([r.latency_ms for r in subset]),
            "median_output_bytes": _median([float(r.output_bytes) for r in subset]),
            "median_query_time_ms": _median(
                [float(r.query_time_ms) for r in subset if r.query_time_ms is not None]
            ),
            "hybrid_paths": float(sum(1 for r in hits if r.ranked_path == "hybrid")),
        }
    return summary


def _rate(records: list[CaseScore], predicate: Any) -> float:
    """Return the fraction of *records* for which *predicate* is true."""
    if not records:
        return 0.0
    return sum(1 for record in records if predicate(record)) / len(records)


def _median(values: list[float]) -> float:
    """Return the median of *values*, or ``0.0`` when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 1)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 1)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the harness, and print the summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Repository to evaluate (defaults to a local corpus)")
    parser.add_argument("--context-dir", help="Context directory (defaults to REPO/.context)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Results per query")
    parser.add_argument(
        "--cold",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the one-shot cold path (default: on)",
    )
    parser.add_argument(
        "--warm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the warm-daemon path (default: on)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="JSONL output path (defaults to ./tool_utility_results.jsonl)",
    )
    parser.add_argument(
        "--no-adversarial",
        action="store_true",
        help="Exclude the adversarial abstention set",
    )
    args = parser.parse_args(argv)

    repo = _default_repo(args.repo)
    if repo is None:
        print(
            "SKIP: evaluation corpus not found. Pass --repo or set CODE_SEARCH_EVAL_REPO.",
            file=sys.stderr,
        )
        return 0

    context_dir = Path(args.context_dir).resolve() if args.context_dir else None
    report = run_evaluation(
        repo=repo,
        context_dir=context_dir,
        limit=args.limit,
        run_cold=args.cold,
        run_warm=args.warm,
        json_out=args.json_out,
        include_adversarial=not args.no_adversarial,
    )
    print(json.dumps(report["summary"], indent=2))
    print(f"JSONL: {report['json_out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
