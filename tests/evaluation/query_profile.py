#!/usr/bin/env python3
"""Profile one warm search query and attribute SQLite cost.

Runs :class:`HybridSearch` in-process against an existing index and reports the
top 30 cumulative ``cProfile`` entries plus per-statement SQLite call counts and
elapsed time. This is the measurement helper the warm-path work uses to prove
that a query no longer scans the whole ``code_chunks`` table.

Run standalone with::

    python tests/evaluation/query_profile.py \
        --repo ~/git/baeldung-tutorials \
        --query ExponentialBackoffRetryFactory --no-model
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DEFAULT_CORPUS_CANDIDATES = (
    Path.home() / "git" / "baeldung-tutorials",
    Path("/media/dhanoopbhaskar/hdd01/home/git/baeldung-tutorials"),
)
DEFAULT_QUERY = "ExponentialBackoffRetryFactory"


def _resolve_repo(explicit: str | None) -> Path | None:
    """Return the corpus root or ``None`` when it is unavailable."""
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


class _SqliteTrace:
    """Collect SQLite statement counts and elapsed time."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.seconds: Counter[str] = Counter()
        self._start: float | None = None
        self._pending = ""

    def __call__(self, statement: str) -> None:
        """Record the end of the previous statement and start the next."""
        now = time.perf_counter()
        if self._start is not None:
            self.seconds[self._pending] += now - self._start
        self._pending = " ".join(statement.split())[:160]
        self.calls[self._pending] += 1
        self._start = now


def _instrument_sqlite(trace: _SqliteTrace) -> Any:
    """Attach *trace* to every new SQLite connection and return the original."""
    original = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original(*args, **kwargs)
        connection.set_trace_callback(trace)
        return connection

    sqlite3.connect = traced_connect  # type: ignore[assignment]
    return original


def profile_query(
    repo: Path,
    context_dir: Path | None,
    query: str,
    limit: int,
    no_model: bool,
) -> dict[str, Any]:
    """Profile one query and return a JSON-serializable report."""
    from code_search.cli.main import _initialize_components
    from code_search.engine.search import HybridSearch

    context = context_dir or (repo / ".context")
    components = _initialize_components(context)
    settings = components["settings"]
    search = components["search"]
    if no_model:
        search = HybridSearch(
            components["db"],
            components["vector_index"],
            components["embedding_gen"],
            settings,
            no_model=True,
        )

    search.search(query, limit=limit)

    trace = _SqliteTrace()
    original_connect = _instrument_sqlite(trace)
    profiler = cProfile.Profile()
    try:
        profiler.enable()
        envelope = search.search(query, limit=limit)
        profiler.disable()
    finally:
        sqlite3.connect = original_connect  # type: ignore[assignment]

    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative")
    stats.print_stats(30)

    return {
        "repo": str(repo),
        "context_dir": str(context),
        "query": query,
        "ranked_path": envelope.get("ranked_path"),
        "query_time_ms": envelope.get("query_time_ms"),
        "sqlite_calls": sum(trace.calls.values()),
        "sqlite_seconds": round(sum(trace.seconds.values()), 3),
        "sqlite_top": [
            {"statement": statement, "calls": count, "seconds": round(trace.seconds[statement], 3)}
            for statement, count in trace.calls.most_common(15)
        ],
        "top_functions": _parse_profile(buffer.getvalue()),
    }


def _parse_profile(text: str) -> list[dict[str, Any]]:
    """Parse the pstats table into structured rows."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6 or not parts[0].isdigit():
            continue
        ncalls, tottime, _percall, cumtime, _percall2, location = parts
        rows.append(
            {
                "ncalls": ncalls,
                "tottime_s": float(tottime),
                "cumtime_s": float(cumtime),
                "function": location.strip(),
            }
        )
    return rows[:30]


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and print the profile report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Repository with an existing index")
    parser.add_argument("--context-dir", help="Context directory (defaults to REPO/.context)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Query to profile")
    parser.add_argument("--limit", type=int, default=10, help="Results per query")
    parser.add_argument("--no-model", action="store_true", help="Profile the lexical path only")
    parser.add_argument("--json-out", type=Path, help="Write the report to this path")
    args = parser.parse_args(argv)

    repo = _resolve_repo(args.repo)
    if repo is None or not (repo / ".context" / "graph.db").is_file():
        print("SKIP: index not found. Pass --repo and index it first.", file=sys.stderr)
        return 0

    context_dir = Path(args.context_dir).resolve() if args.context_dir else None
    report = profile_query(repo, context_dir, args.query, args.limit, args.no_model)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
