#!/usr/bin/env python3
"""Cross-repository baseline harness for ranking, latency, and footprint.

Indexes every active repository in the matrix from
``tests/evaluation/matrix_ground_truth.py`` and records the metrics the
improvement work is judged on:

* NDCG@10, top-1, and top-3 over the labelled positive queries.
* Production/test composition of the top 10 and the rate at which negative
  queries abstain or return weak results.
* Content-type composition (code/configuration/documentation) of the top 10.
* Index build time, first-query latency, and warm query latency.
* Index footprint broken down by graph, vectors, and auxiliary databases.
* Internal-edge resolution counts (precision needs a labelled sample and is
  recorded by the graph-precision phase).

The harness performs no ranking changes. Its JSON output is the baseline that
later phases compare against. Process-level cold-start phases are measured by
``tests/evaluation/cold_start_benchmark.py``; this harness records index-build
and first-query time separately.

Run standalone with::

    python -m tests.evaluation.matrix_eval
    python -m tests.evaluation.matrix_eval --output tests/evaluation/matrix_baseline.json
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import FIXTURES_DIR, _indexed_components
from tests.evaluation.matrix_ground_truth import (
    CATEGORIES,
    MATRIX_REPOS,
    MatrixQuery,
    MatrixRepo,
    active_repos,
    queries_for,
)

DEFAULT_LIMIT = 10

#: Seconds per character used to report an approximate response token count.
#: The code-search surface has no tokenizer dependency, so the baseline records
#: this deterministic estimate rather than pulling in a model tokenizer.
CHARS_PER_TOKEN = 4


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _gain(result: dict[str, Any], query: MatrixQuery) -> int:
    """Return the graded relevance of *result* for *query*.

    Explicit grade pairs take precedence; otherwise the first expected file is
    gain 2, alternatives are gain 1, and everything else is 0. An expected FQN
    narrows a matching file to the labelled symbol.
    """
    file_path = str(result.get("file_path", ""))
    result_fqn = str(result.get("fqn") or "")
    if query.grades:
        gains = [
            gain
            for fragment, gain in query.grades
            if fragment in file_path
            and (query.expected_fqn is None or query.expected_fqn in result_fqn)
        ]
        return max(gains, default=0)
    for index, fragment in enumerate(query.expected_files):
        if fragment not in file_path:
            continue
        if query.expected_fqn and query.expected_fqn not in result_fqn:
            continue
        return 2 if index == 0 else 1
    return 0


def _ideal_gains(query: MatrixQuery, limit: int) -> list[int]:
    """Return the ideal gain vector for *query*, truncated to *limit*."""
    if query.grades:
        gains = [gain for _, gain in query.grades]
    else:
        gains = [2, *([1] * max(0, len(query.expected_files) - 1))]
    return sorted(gains, reverse=True)[:limit]


def _ndcg_at_k(results: list[dict[str, Any]], query: MatrixQuery, limit: int) -> float | None:
    """Return NDCG@*limit* for *query*, or ``None`` when it has no expectations."""
    ideal = _ideal_gains(query, limit)
    if not ideal:
        return None
    actual_gains = [_gain(result, query) for result in results[:limit]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(actual_gains))
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return dcg / idcg if idcg else None


def _rank(results: list[dict[str, Any]], query: MatrixQuery) -> int | None:
    """Return the 1-based rank of the first relevant result, or ``None``."""
    for index, result in enumerate(results, start=1):
        if _gain(result, query) > 0:
            return index
    return None


def _response_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Return compact response size and composition for *results*."""
    from code_search.engine.response_service import compact_results

    compact = compact_results(results, max_snippet_lines=DEFAULT_LIMIT)
    text = json.dumps(compact, default=str)
    composition = Counter(str(result.get("content_type") or "code") for result in results)
    return {
        "response_chars": len(text),
        "response_tokens_estimated": math.ceil(len(text) / CHARS_PER_TOKEN),
        "test_results": sum(1 for result in results if result.get("is_test_file")),
        "production_results": sum(1 for result in results if not result.get("is_test_file")),
        "content_composition": dict(sorted(composition.items())),
    }


def _weak_response(envelope: dict[str, Any]) -> bool:
    """Return whether the response abstained or labelled every result weak."""
    if envelope.get("no_match") or not envelope.get("results"):
        return True
    return all(result.get("below_threshold") for result in envelope["results"])


def _evaluate_query(search: Any, query: MatrixQuery, limit: int) -> dict[str, Any]:
    """Run one labelled query and return its metric record."""
    started = time.monotonic()
    if query.content_scope:
        envelope = search.search(query.query, limit=limit, content=query.content_scope)
    else:
        envelope = search.search(query.query, limit=limit)
    latency_ms = round((time.monotonic() - started) * 1000, 1)
    results = envelope.get("results") or []
    rank = _rank(results, query)
    weak = _weak_response(envelope)
    passed = (
        weak and rank is None if query.expect_weak else rank is not None and rank <= query.top_k
    )
    record: dict[str, Any] = {
        "query": query.query,
        "category": query.category,
        "content_scope": query.content_scope,
        "expected": list(query.expected_files),
        "expected_fqn": query.expected_fqn,
        "rank": rank,
        "top_k": query.top_k,
        "passed": passed,
        "ndcg_at_10": _ndcg_at_k(results, query, limit),
        "query_time_ms": envelope.get("query_time_ms"),
        "latency_ms": latency_ms,
        "no_match": bool(envelope.get("no_match")),
        "weak": weak,
        "result_count": len(results),
        "model_status": envelope.get("model_status"),
    }
    record.update(_response_metrics(results))
    return record


def _index_stats(
    components: dict[str, Any],
    context_dir: Path,
    index_build_ms: float,
) -> dict[str, Any]:
    """Return chunk, graph, and footprint statistics for one repository."""
    from code_search.engine.parser import ASTParser

    db = components["db"]
    with db.connect() as conn:
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        test_chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM code_chunks WHERE is_test = 1;"
        ).fetchone()["n"]
        content_rows = conn.execute(
            "SELECT content_type, COUNT(*) AS n FROM code_chunks GROUP BY content_type;"
        ).fetchall()
        symbol_count = conn.execute("SELECT COUNT(*) AS n FROM symbols;").fetchone()["n"]
        edge_rows = conn.execute(
            "SELECT edge_type, resolved, COUNT(*) AS n FROM graph_edges "
            "GROUP BY edge_type, resolved;"
        ).fetchall()
        tier_rows = conn.execute(
            "SELECT COALESCE(resolution_tier, 'unknown') AS tier, COUNT(*) AS n "
            "FROM graph_edges GROUP BY tier;"
        ).fetchall()

    size_breakdown: Counter[str] = Counter()
    if context_dir.is_dir():
        for path in context_dir.rglob("*"):
            if not path.is_file():
                continue
            name = path.name
            if name.startswith("graph.db"):
                bucket = "graph"
            elif name.startswith("vectors."):
                bucket = "vectors"
            elif name.startswith("session.db"):
                bucket = "session"
            elif name.startswith("audit.db"):
                bucket = "audit"
            else:
                bucket = "other"
            size_breakdown[bucket] += path.stat().st_size

    edges_resolved = sum(row["n"] for row in edge_rows if row["resolved"])
    edges_unresolved = sum(row["n"] for row in edge_rows if not row["resolved"])
    return {
        "index_build_ms": round(index_build_ms, 1),
        "chunks": chunk_count,
        "test_chunks": test_chunks,
        "content_chunks": {row["content_type"]: row["n"] for row in content_rows},
        "symbols": symbol_count,
        "edges_resolved": edges_resolved,
        "edges_unresolved": edges_unresolved,
        "edges_by_type": {
            edge_type: sum(row["n"] for row in edge_rows if row["edge_type"] == edge_type)
            for edge_type in sorted({row["edge_type"] for row in edge_rows})
        },
        "resolution_tiers": {row["tier"]: row["n"] for row in tier_rows},
        "edge_precision": "not_measured",
        "size_bytes": dict(sorted(size_breakdown.items())),
        "size_bytes_total": sum(size_breakdown.values()),
        "discovered_files": len(
            ASTParser().discover_files(
                components["repo"],
                exclusion_patterns=set(),
                include_resources=True,
                resource_extensions=components["settings"].resource_extensions,
                index_prose=components["settings"].index_prose,
            )
        ),
    }


def _repo_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the per-query records for one repository."""
    ranked = [record for record in records if record["expected"]]
    negatives = [record for record in records if not record["expected"]]
    ndcg_values = [record["ndcg_at_10"] for record in ranked if record["ndcg_at_10"] is not None]
    latencies = [record["latency_ms"] for record in records]
    return {
        "queries": len(records),
        "ndcg_at_10": statistics.fmean(ndcg_values) if ndcg_values else None,
        "top1": (
            sum(1 for record in ranked if record["rank"] == 1) / len(ranked) if ranked else None
        ),
        "top3": (
            sum(1 for record in ranked if record["rank"] is not None and record["rank"] <= 3)
            / len(ranked)
            if ranked
            else None
        ),
        "negative_weak_rate": (
            sum(1 for record in negatives if record["weak"]) / len(negatives) if negatives else None
        ),
        "production_results": sum(record["production_results"] for record in records),
        "test_results": sum(record["test_results"] for record in records),
        "first_query_latency_ms": latencies[0] if latencies else None,
        "warm_latency_p50_ms": statistics.median(latencies[1:]) if len(latencies) > 1 else None,
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "response_chars": sum(record["response_chars"] for record in records),
    }


def _aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return macro averages across repositories (each repository counts once)."""
    ndcg = [
        repo["metrics"]["ndcg_at_10"]
        for repo in reports
        if repo["metrics"]["ndcg_at_10"] is not None
    ]
    top1 = [repo["metrics"]["top1"] for repo in reports if repo["metrics"]["top1"] is not None]
    top3 = [repo["metrics"]["top3"] for repo in reports if repo["metrics"]["top3"] is not None]
    negative = [
        repo["metrics"]["negative_weak_rate"]
        for repo in reports
        if repo["metrics"]["negative_weak_rate"] is not None
    ]
    tests = sum(repo["metrics"]["test_results"] for repo in reports)
    production = sum(repo["metrics"]["production_results"] for repo in reports)
    composition: Counter[str] = Counter()
    for repo in reports:
        for record in repo["queries"]:
            composition.update(record.get("content_composition") or {})
    return {
        "repos_measured": len(reports),
        "ndcg_at_10": statistics.fmean(ndcg) if ndcg else None,
        "top1": statistics.fmean(top1) if top1 else None,
        "top3": statistics.fmean(top3) if top3 else None,
        "negative_weak_rate": statistics.fmean(negative) if negative else None,
        "production_share": production / (production + tests) if production + tests else None,
        "test_results": tests,
        "production_results": production,
        "content_composition": dict(sorted(composition.items())),
        "index_bytes_total": sum(repo["index"]["size_bytes_total"] for repo in reports),
        "chunks_total": sum(repo["index"]["chunks"] for repo in reports),
        "index_build_ms_total": round(sum(repo["index"]["index_build_ms"] for repo in reports), 1),
    }


def _measure_repo(repo: MatrixRepo, work_dir: Path) -> dict[str, Any]:
    """Index one matrix repository and evaluate every labelled query."""
    copy_dir = work_dir / repo.id
    shutil.copytree(FIXTURES_DIR / str(repo.fixture), copy_dir)
    # A non-Git matrix entry must stay non-Git even if the fixture ever carries
    # a .git directory.
    if repo.id == "non-git":
        shutil.rmtree(copy_dir / ".git", ignore_errors=True)

    started = time.monotonic()
    components = _indexed_components(copy_dir, copy_dir / ".context")
    index_build_ms = (time.monotonic() - started) * 1000.0

    records = [
        _evaluate_query(components["search"], query, DEFAULT_LIMIT)
        for query in queries_for(repo.id)
    ]
    return {
        "id": repo.id,
        "label": repo.label,
        "languages": list(repo.languages),
        "tier": repo.tier,
        "notes": repo.notes,
        "index": _index_stats(components, copy_dir / ".context", index_build_ms),
        "metrics": _repo_metrics(records),
        "queries": records,
    }


def _measure_unsupported(repo: MatrixRepo, work_dir: Path) -> dict[str, Any]:
    """Index an unsupported-language fixture and record that discovery skipped it."""
    from code_search.engine.parser import ASTParser

    copy_dir = work_dir / repo.id
    shutil.copytree(FIXTURES_DIR / str(repo.fixture), copy_dir)
    discovered = ASTParser().discover_files(copy_dir)
    started = time.monotonic()
    components = _indexed_components(copy_dir, copy_dir / ".context")
    index_build_ms = (time.monotonic() - started) * 1000.0
    return {
        "id": repo.id,
        "label": repo.label,
        "languages": [],
        "tier": repo.tier,
        "notes": repo.notes,
        "index": _index_stats(components, copy_dir / ".context", index_build_ms),
        "discovered_files": len(discovered),
        "metrics": _repo_metrics([]),
        "queries": [],
    }


def run_matrix(
    work_dir: Path,
    repos: tuple[MatrixRepo, ...] | None = None,
) -> dict[str, Any]:
    """Run the full matrix and return a JSON-serializable baseline report.

    Args:
        work_dir: Scratch directory; each repository is copied and indexed under
            its own subdirectory.
        repos: Optional repository subset; defaults to every active entry.

    Returns:
        A report with per-repository query records and metrics, macro
        aggregates, and the pending entries that were skipped.
    """
    selected = repos if repos is not None else active_repos()
    measured: list[dict[str, Any]] = []
    for repo in selected:
        if repo.pending or not repo.fixture:
            continue
        if repo.tier == "unsupported":
            measured.append(_measure_unsupported(repo, work_dir))
        else:
            measured.append(_measure_repo(repo, work_dir))

    pending = [
        {"id": repo.id, "label": repo.label, "notes": repo.notes}
        for repo in MATRIX_REPOS
        if repo.pending
    ]
    failures = [
        {
            "repo": report["id"],
            "query": record["query"],
            "category": record["category"],
            "rank": record["rank"],
            "expected": record["expected"],
        }
        for report in measured
        for record in report["queries"]
        if not record["passed"]
    ]
    return {
        "generated_at": _now_iso(),
        "limit": DEFAULT_LIMIT,
        "categories": list(CATEGORIES),
        "repos": measured,
        "pending": pending,
        "aggregate": _aggregate([report for report in measured if report["queries"]]),
        "failures": failures,
    }


def _fmt(value: float | None) -> str:
    """Format a metric for the summary table."""
    return "-" if value is None else f"{value:.2f}"


def format_report(report: dict[str, Any]) -> str:
    """Render a compact human-readable summary of *report*."""
    lines = ["=" * 72, "Repository Matrix Baseline", "=" * 72]
    for repo in report["repos"]:
        metrics = repo["metrics"]
        index = repo["index"]
        lines.append(
            f"{repo['id']:<24} ndcg@10={_fmt(metrics.get('ndcg_at_10')):>5} "
            f"top1={_fmt(metrics.get('top1')):>5} "
            f"top3={_fmt(metrics.get('top3')):>5} "
            f"chunks={index.get('chunks', 0):>5} "
            f"index={index.get('index_build_ms', 0):>8.0f}ms"
        )
    aggregate = report["aggregate"]
    lines.append("-" * 72)
    lines.append(
        f"{'macro':<24} ndcg@10={_fmt(aggregate.get('ndcg_at_10')):>5} "
        f"top1={_fmt(aggregate.get('top1')):>5} "
        f"top3={_fmt(aggregate.get('top3')):>5} "
        f"chunks={aggregate.get('chunks_total', 0):>5}"
    )
    if report["pending"]:
        lines.append(f"Pending entries: {', '.join(item['id'] for item in report['pending'])}")
    lines.append(f"Failures: {len(report['failures'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: build the matrix and print/write the baseline."""
    parser = argparse.ArgumentParser(description="Run the repository matrix baseline")
    parser.add_argument("--output", type=Path, default=None, help="Write the report JSON here")
    parser.add_argument(
        "--repo",
        action="append",
        default=None,
        help="Limit the run to a repository id (repeatable)",
    )
    args = parser.parse_args(argv)

    selected = active_repos()
    if args.repo:
        wanted = set(args.repo)
        selected = tuple(repo for repo in selected if repo.id in wanted)
        unknown = wanted - {repo.id for repo in selected}
        if unknown:
            parser.error(f"unknown or pending repository id(s): {', '.join(sorted(unknown))}")

    with tempfile.TemporaryDirectory(prefix="matrix_eval_") as tmp:
        report = run_matrix(Path(tmp), repos=selected)

    print(format_report(report))
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
