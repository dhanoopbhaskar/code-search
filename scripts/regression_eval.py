"""Regression eval for the agent-facing surfaces.

The harness asserts the contracts the improvement plan depends on: payload
budgets, overload resolution, exhaustive latency relative to ``rg``, strict
abstention, and (optionally) labelled NL precision@5. It runs the real CLI in
``--no-daemon`` mode so the measured bytes and timings are what an agent
actually receives.

Usage::

    python scripts/regression_eval.py --repo test-repo
    python scripts/regression_eval.py --repo test-repo --reindex
    python scripts/regression_eval.py --repo test-repo --labels eval/labels.json

The labels file is a list of ``{"query": ..., "expected": [substring, ...]}``
rows. The harness is not collected by pytest; it is a ``make eval`` target.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CHARS_PER_TOKEN = 4


@dataclass
class Check:
    """One measured regression check."""

    name: str
    passed: bool
    detail: str


def _cli(repo: Path, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """Run one ``code-search`` invocation against *repo*."""
    command = [
        sys.executable,
        "-m",
        "code_search.cli.main",
        "--context-dir",
        str(repo / ".context"),
        "--no-daemon",
        *args,
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(repo),
    )


def _json(command: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Decode a CLI JSON response, or return an empty dict on failure."""
    try:
        value = json.loads(command.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _ensure_index(repo: Path, reindex: bool) -> None:
    """Build the index when missing (or when ``--reindex`` is requested)."""
    graph = repo / ".context" / "graph.db"
    if graph.is_file() and not reindex:
        return
    result = _cli(repo, "index", "--path", str(repo), "--force", timeout=900.0)
    if result.returncode != 0:
        raise SystemExit(f"index failed: {result.stderr or result.stdout}")


def _payload_chars(payload: dict[str, Any]) -> int:
    """Return the serialized size of *payload*."""
    return len(json.dumps(payload, default=str))


def _first_source(repo: Path) -> str | None:
    """Return a repo-relative source path for outline/affected checks."""
    for suffix in (".java", ".py", ".ts", ".go", ".cs", ".kt"):
        for path in sorted(repo.rglob(f"*{suffix}")):
            if ".context" in path.parts:
                continue
            return str(path.relative_to(repo))
    return None


def _time_command(command: list[str], cwd: Path, repeats: int = 3) -> float:
    """Return the best wall-clock time of *command* over *repeats*."""
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        subprocess.run(command, cwd=str(cwd), capture_output=True, check=False)
        best = min(best, time.perf_counter() - started)
    return best


def _exhaustive_check(repo: Path, literal: str, max_ratio: float) -> Check:
    """Compare in-process exhaustive latency with ``rg`` when available.

    CLI startup (model/component initialisation) is excluded so the measurement
    reflects the scan itself: the inline probe initialises components once and
    times only ``HybridSearch.search(mode="exhaustive")``.
    """
    probe = (
        "import time\n"
        "from pathlib import Path\n"
        "from code_search.cli.main import _initialize_components\n"
        f"comps = _initialize_components(Path({str(repo / '.context')!r}), load_vectors=False)\n"
        "hs = comps['search']\n"
        "best = 10.0\n"
        f"for _ in range(3):\n"
        f"    started = time.perf_counter()\n"
        f"    hs.search({literal!r}, mode='exhaustive', matching='literal', limit=1)\n"
        "    best = min(best, time.perf_counter() - started)\n"
        "print(best * 1000)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
        search_ms = float(result.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return Check("exhaustive latency", False, "in-process probe failed")

    rg = shutil.which("rg")
    if rg is None:
        return Check(
            "exhaustive latency",
            True,
            f"{search_ms:.0f} ms (rg unavailable; ratio not checked)",
        )
    rg_time = _time_command([rg, "-l", literal, str(repo)], repo)
    rg_ms = rg_time * 1000
    ratio = search_ms / max(rg_ms, 1e-6)
    return Check(
        "exhaustive latency",
        ratio <= max_ratio,
        f"{search_ms:.0f} ms vs rg {rg_ms:.0f} ms (ratio {ratio:.1f}x, max {max_ratio:.1f}x)",
    )


def _overload_checks(repo: Path, references: list[str]) -> list[Check]:
    """Assert every configured signature-qualified reference resolves."""
    checks: list[Check] = []
    for reference in references:
        result = _cli(repo, "symbol", reference, "--json")
        data = _json(result)
        checks.append(
            Check(
                f"resolve {reference}",
                bool(data.get("matched")) and result.returncode == 0,
                f"outcome={data.get('outcome')} exit={result.returncode}",
            )
        )
    return checks


def _precision_checks(repo: Path, labels_path: Path | None) -> list[Check]:
    """Measure precision@5 for a labelled query set, when supplied."""
    if labels_path is None:
        return []
    rows = json.loads(labels_path.read_text(encoding="utf-8"))
    checks: list[Check] = []
    for row in rows:
        query = str(row["query"])
        expected = [str(item) for item in row.get("expected", [])]
        result = _cli(repo, "search", query, "--json", "--limit", "5")
        data = _json(result)
        haystack = " ".join(
            f"{item.get('fqn', '')} {item.get('file_path', '')}"
            for item in data.get("results") or []
        )
        hits = sum(1 for item in expected if item in haystack)
        precision = hits / max(len(expected), 1)
        checks.append(
            Check(
                f"precision@5 {query!r}",
                precision >= float(row.get("min", 0.6)),
                f"{precision:.2f}",
            )
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    """Run the regression eval and print a pass/fail table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="test-repo", help="Corpus to evaluate")
    parser.add_argument("--reindex", action="store_true", help="Force a fresh index first")
    parser.add_argument("--budget-search-kib", type=int, default=8, help="Ranked payload cap")
    parser.add_argument(
        "--budget-paths-kib", type=int, default=3, help="Ranked paths-only payload cap"
    )
    parser.add_argument("--budget-outline-kib", type=int, default=15, help="Outline payload cap")
    parser.add_argument("--budget-affected-kib", type=int, default=15, help="Affected payload cap")
    parser.add_argument("--budget-ask-kib", type=int, default=8, help="Ask payload cap")
    parser.add_argument(
        "--max-exhaustive-ratio", type=float, default=10.0, help="Max exhaustive/rg ratio"
    )
    parser.add_argument(
        "--overload",
        action="append",
        default=[],
        help="Signature-qualified reference that must resolve (repeatable)",
    )
    parser.add_argument("--labels", type=Path, help="Labelled NL precision JSON")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")
    _ensure_index(repo, args.reindex)
    checks: list[Check] = []

    source = _first_source(repo)
    if source is not None:
        outline = _cli(repo, "outline", source, "--json")
        outline_chars = len(outline.stdout)
        checks.append(
            Check(
                "outline payload",
                outline_chars <= args.budget_outline_kib * 1024,
                f"{outline_chars} B (max {args.budget_outline_kib} KiB)",
            )
        )
        affected = _cli(repo, "affected", source, "--json")
        affected_chars = len(affected.stdout)
        checks.append(
            Check(
                "affected payload",
                affected_chars <= args.budget_affected_kib * 1024,
                f"{affected_chars} B (max {args.budget_affected_kib} KiB)",
            )
        )

    search = _cli(repo, "search", "validate token", "--json", "--limit", "10")
    search_chars = len(search.stdout)
    checks.append(
        Check(
            "search payload",
            search_chars <= args.budget_search_kib * 1024,
            f"{search_chars} B (max {args.budget_search_kib} KiB)",
        )
    )
    paths = _cli(repo, "search", "validate token", "--json", "--paths-only", "--limit", "10")
    paths_chars = len(paths.stdout)
    checks.append(
        Check(
            "search paths-only payload",
            paths_chars <= args.budget_paths_kib * 1024,
            f"{paths_chars} B (max {args.budget_paths_kib} KiB)",
        )
    )

    ask = _cli(repo, "ask", "validate token", "--json")
    ask_payload = _json(ask)
    ask_chars = len(ask.stdout)
    checks.append(
        Check(
            "ask payload",
            ask_chars <= args.budget_ask_kib * 1024 and "answer_type" in ask_payload,
            f"{ask_chars} B, answer_type={ask_payload.get('answer_type')}",
        )
    )

    negative = _json(_cli(repo, "search", "quantum flux capacitor", "--strict", "--json"))
    checks.append(
        Check(
            "strict abstention",
            bool(negative.get("no_match")),
            f"no_match={negative.get('no_match')} confidence={negative.get('confidence')}",
        )
    )

    checks.append(_exhaustive_check(repo, "User", args.max_exhaustive_ratio))
    checks.extend(_overload_checks(repo, args.overload))
    checks.extend(_precision_checks(repo, args.labels))

    width = max(len(check.name) for check in checks)
    failed = 0
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status}  {check.name:<{width}}  {check.detail}")
        failed += 0 if check.passed else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
