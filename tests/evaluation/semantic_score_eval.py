#!/usr/bin/env python3
"""Zero-semantic-score evaluation harness.

Indexes the hermetic ``semantic_vector`` fixture, runs the labelled conceptual
queries, and reports the number of *unexplained* zero semantic scores among the
returned results: a result whose ``vector_score`` is ``0.0`` while its
``semantic_contribution`` claims ``semantic`` (a contradiction). A zero is
explained when the result is explicitly labelled ``lexical_only`` / ``deferred``
/ ``unavailable``.

Run standalone::

    python -m tests.evaluation.semantic_score_eval

Exits non-zero when a healthy layer produces an unexplained zero or a labelled
ground-truth chunk is not semantically retrieved.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import _GATE_OFF, FIXTURES_DIR, _indexed_components

DEFAULT_FIXTURE = "semantic_vector"
DEFAULT_LIMIT = 5
CORPUS_LABEL = "semantic fixture"

#: Ground-truth files per conceptual query (mirrors
#: ``tests/integration/test_semantic_vector.py``).
GROUND_TRUTH: dict[str, tuple[str, ...]] = {
    "token-expiration": (
        "session/SessionWindowPolicy.java",
        "session/ConnectionLifetimePolicy.java",
        "session/AuthProperties.java",
    ),
    "email-registered": (
        "identity/EnrollmentRegistry.java",
        "identity/IdentityDirectory.java",
    ),
    "entity-response": (
        "presentation/ModelViewFactory.java",
        "presentation/ArticleContent.java",
    ),
    "disconnected-session": (
        "session/ConnectionLifetimePolicy.java",
        "session/SessionWindowPolicy.java",
    ),
}

QUERIES: dict[str, str] = {
    "token-expiration": "how long can a user stay signed in before their session token expires",
    "email-registered": "reject creating an account when the email is already registered",
    "entity-response": "convert domain entities into API response objects",
    "disconnected-session": "when does a logged-in user get disconnected",
}


def evaluate(
    components: dict[str, Any],
    limit: int = DEFAULT_LIMIT,
    corpus: str = CORPUS_LABEL,
) -> dict[str, Any]:
    """Run the labelled queries and count unexplained zero semantic scores.

    Args:
        components: Indexed components (from ``_indexed_components``).
        limit: Results per query.
        corpus: Corpus label echoed into the report.

    Returns:
        The zero-score report (``corpus``, ``limit``, ``healthy``,
        ``unexplained_zero``, ``ground_truth_missing``, ``queries``).
    """
    search = components["search"]
    healthy = True
    unexplained_zero = 0
    ground_truth_missing = 0
    per_query: list[dict[str, Any]] = []
    for name, query in QUERIES.items():
        envelope = search.search(query, limit=limit)
        vector_health = bool(envelope.get("vector_health", False))
        if not vector_health:
            healthy = False
        results = envelope.get("results", [])
        zero = [r for r in results if float(r.get("vector_score", 0.0)) == 0.0]
        unexplained = [r for r in zero if r.get("semantic_contribution") == "semantic"]
        unexplained_zero += len(unexplained)
        semantic = [r for r in results if r.get("vector_retrieved") is True]
        expected = GROUND_TRUTH[name]
        relevant_semantic = [
            r for r in semantic if any(path in r.get("file_path", "") for path in expected)
        ]
        if vector_health and not relevant_semantic:
            ground_truth_missing += 1
        per_query.append(
            {
                "query": name,
                "vector_health": vector_health,
                "results": len(results),
                "zero_scores": len(zero),
                "unexplained_zero": len(unexplained),
                "semantic_results": len(semantic),
                "ground_truth_semantic": len(relevant_semantic),
            }
        )
    return {
        "corpus": corpus,
        "limit": limit,
        "healthy": healthy,
        "unexplained_zero": unexplained_zero,
        "ground_truth_missing": ground_truth_missing,
        "queries": per_query,
    }


def format_report(report: dict[str, Any]) -> str:
    """Render the human-readable summary table for *report*."""
    lines = [
        "=" * 60,
        "Zero-Semantic-Score Evaluation",
        f"Corpus: {report['corpus']}",
        "=" * 60,
        f"Healthy layer           : {report['healthy']}",
        f"unexplained_zero        : {report['unexplained_zero']}",
        f"ground_truth_missing    : {report['ground_truth_missing']}",
        "-" * 60,
    ]
    for entry in report["queries"]:
        lines.append(
            f"{entry['query']:<22} results={entry['results']:<3} "
            f"zeros={entry['zero_scores']:<3} unexplained={entry['unexplained_zero']:<3} "
            f"semantic={entry['semantic_results']:<3} "
            f"ground_truth_semantic={entry['ground_truth_semantic']}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


def build_fixture_components(work_dir: Path, fixture: str = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Copy *fixture* into *work_dir* and index it with the relevance gate off."""
    repo = work_dir / "semantic_vector_repo"
    shutil.copytree(FIXTURES_DIR / fixture, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: index the hermetic corpus, evaluate, and report."""
    parser = argparse.ArgumentParser(description="Evaluate zero semantic scores")
    parser.add_argument("--repo", type=Path, default=None, help="External repo to index")
    parser.add_argument("--output", type=Path, default=None, help="Write report JSON here")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    if args.repo is not None:
        repo = args.repo.resolve()
        components = _indexed_components(repo, repo / ".context", settings_kwargs=_GATE_OFF)
        report = evaluate(components, limit=args.limit, corpus=str(repo))
    else:
        with tempfile.TemporaryDirectory(prefix="semantic_score_eval_") as tmp:
            components = build_fixture_components(Path(tmp))
            report = evaluate(components, limit=args.limit)

    print(format_report(report))
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n")

    if report["healthy"] and (report["unexplained_zero"] or report["ground_truth_missing"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
