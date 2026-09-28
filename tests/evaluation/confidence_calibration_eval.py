#!/usr/bin/env python3
"""Calibration evaluation harness for per-result confidence.

Indexes the in-repo fixtures (or an external ``--repo`` checkout), runs the
labelled ground-truth queries, and reports band-relevance agreement, high-band
precision, high-band recall, and primary-high share. The same metrics are
computed for the pre-change base blend (``confidence_score``) so the
calibration's improvement over the baseline is visible.

The harness is importable: ``tests/integration/test_confidence_calibration.py``
calls :func:`evaluate` to enforce the CI floors without re-implementing the
metrics. Run standalone with::

    python tests/evaluation/confidence_calibration_eval.py
    python tests/evaluation/confidence_calibration_eval.py --repo /path/to/repo
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

from src.engine.confidence import confidence_band, confidence_score
from tests.conftest import FIXTURES_DIR, _indexed_components
from tests.evaluation.confidence_ground_truth import (
    GROUND_TRUTH_CASES,
    GroundTruthCase,
)

DEFAULT_FIXTURES = ("quality_defects", "relevance")
DEFAULT_LIMIT = 10
CORPUS_LABEL = "quality_defects + relevance fixtures"

#: CI metric floors.
FLOORS: dict[str, float] = {
    "high_band_precision": 0.85,
    "high_band_recall": 0.80,
    "primary_high_share": 0.80,
}


def _is_relevant(result: dict[str, Any], case: GroundTruthCase) -> bool:
    """Return whether *result* is labelled relevant for *case*.

    Relevance is matched against the result's file path (and FQN) using the
    case's ``relevant_patterns`` / ``irrelevant_patterns``.
    """
    haystack = f"{result.get('file_path', '')} {result.get('fqn', '')}"
    if any(pattern in haystack for pattern in case.irrelevant_patterns):
        return False
    return any(pattern in haystack for pattern in case.relevant_patterns)


def _find_expected(results: list[dict[str, Any]], case: GroundTruthCase) -> dict[str, Any] | None:
    """Locate the expected primary definition among *results*.

    A result matches when its file contains ``expected_file`` and its FQN or
    content carries the expected symbol's trailing name. The exact-FQN hit is
    preferred over the containing-class fallback.
    """
    if not case.expected_file:
        return None
    leaf = case.expected_fqn.rsplit(".", 1)[-1]
    fallback: dict[str, Any] | None = None
    for result in results:
        if case.expected_file not in result.get("file_path", ""):
            continue
        if leaf in result.get("fqn", ""):
            return result
        if fallback is None and leaf in result.get("content", ""):
            fallback = result
    return fallback


def _short_symbol_name(fqn: str) -> str:
    """Return the trailing symbol name of *fqn* (signature stripped)."""
    normalized = fqn.split("(", 1)[0]
    if "::" in normalized:
        normalized = normalized.rsplit("::", 1)[-1]
    return normalized.rsplit(".", 1)[-1]


def _definition_outranks_reference(results: list[dict[str, Any]]) -> bool:
    """Return whether every definition outranks a same-named reference.

    Results are grouped by short symbol name; when a group holds both a
    definition and a reference, the definition's confidence must be strictly
    higher. Groups without both roles are ignored (vacuously true).
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_name.setdefault(_short_symbol_name(result.get("fqn", "")), []).append(result)
    for group in by_name.values():
        definitions = [r["confidence"] for r in group if r.get("role") == "definition"]
        references = [r["confidence"] for r in group if r.get("role") == "reference"]
        if definitions and references and max(definitions) <= max(references):
            return False
    return True


def _subwords_by_chunk(db: Any, chunk_ids: list[int]) -> dict[int, list[str]]:
    """Fetch the indexed sub-words for *chunk_ids* (baseline scoring input)."""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" for _ in chunk_ids)
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT id, subwords FROM code_chunks WHERE id IN ({placeholders});",
            list(chunk_ids),
        ).fetchall()
    return {int(row["id"]): (row["subwords"] or "").split() for row in rows}


def evaluate(
    components: dict[str, Any],
    cases: tuple[GroundTruthCase, ...] = GROUND_TRUTH_CASES,
    limit: int = DEFAULT_LIMIT,
    corpus: str = CORPUS_LABEL,
) -> dict[str, Any]:
    """Run the ground-truth queries and compute the calibration metrics.

    Args:
        components: Indexed components (from ``_indexed_components``).
        cases: The labelled ground-truth cases.
        limit: Results per query.
        corpus: Corpus label echoed into the report.

    Returns:
        The calibration report (``summary`` + per-query ``cases``).
    """
    from src.engine.search import decompose_query

    search = components["search"]
    settings = components["settings"]
    db = components["db"]
    high_floor = settings.confidence_high_floor
    medium_floor = settings.confidence_medium_floor

    report_cases: dict[str, dict[str, Any]] = {}
    total_high = 0
    total_high_relevant = 0
    agreement_hits = 0
    agreement_total = 0
    baseline_agreement_hits = 0
    baseline_high = 0
    baseline_high_relevant = 0
    primary_total = 0
    primary_high = 0
    primary_found = 0
    all_outranks = True

    for case in cases:
        envelope = search.search(case.query, limit=limit)
        results = envelope["results"]
        query_subwords = decompose_query(case.query, settings.filter_stopwords)
        subwords = _subwords_by_chunk(db, [r["chunk_id"] for r in results])

        expected = _find_expected(results, case)
        outranks = _definition_outranks_reference(results)
        all_outranks = all_outranks and outranks

        case_high = [r for r in results if r["confidence_band"] == "high"]
        case_high_relevant = [r for r in case_high if _is_relevant(r, case)]
        total_high += len(case_high)
        total_high_relevant += len(case_high_relevant)

        for result in results:
            relevant = _is_relevant(result, case)
            baseline = confidence_score(
                query_subwords, subwords.get(result["chunk_id"], []), result["vector_score"]
            )
            baseline_band = confidence_band(baseline, high_floor, medium_floor)
            if baseline_band == "high":
                baseline_high += 1
                if relevant:
                    baseline_high_relevant += 1

        expected_high = bool(expected and expected["confidence_band"] == "high")
        if expected is not None:
            baseline_expected = confidence_score(
                query_subwords,
                subwords.get(expected["chunk_id"], []),
                expected["vector_score"],
            )
            baseline_expected_high = (
                confidence_band(baseline_expected, high_floor, medium_floor) == "high"
            )
        else:
            baseline_expected_high = False
        # Band-relevance agreement: the expected definition's band must agree
        # with its label (high for primary cases, not-high for peripheral ones).
        if expected_high == case.must_be_high:
            agreement_hits += 1
        if baseline_expected_high == case.must_be_high:
            baseline_agreement_hits += 1
        agreement_total += 1
        if case.must_be_high:
            primary_total += 1
            if expected is not None:
                primary_found += 1
                if expected_high:
                    primary_high += 1

        report_cases[case.query] = {
            "expected_fqn": case.expected_fqn,
            "expected_band": "high" if case.must_be_high else "not_high",
            "actual_band": expected["confidence_band"] if expected else None,
            "actual_confidence": expected["confidence"] if expected else None,
            "definition_outranks_reference": outranks,
            "high_results": len(case_high),
            "high_results_relevant": len(case_high_relevant),
        }

    high_band_precision = total_high_relevant / total_high if total_high else 1.0
    high_band_recall = primary_high / primary_total if primary_total else 0.0
    primary_high_share = primary_high / primary_found if primary_found else 0.0
    band_relevance_agreement = agreement_hits / agreement_total if agreement_total else 0.0
    baseline_band_relevance_agreement = (
        baseline_agreement_hits / agreement_total if agreement_total else 0.0
    )
    baseline_high_band_precision = baseline_high_relevant / baseline_high if baseline_high else 1.0

    targets_met = {
        "high_band_precision_gte_0_85": high_band_precision >= FLOORS["high_band_precision"],
        "high_band_recall_gte_0_80": high_band_recall >= FLOORS["high_band_recall"],
        "primary_high_share_gte_0_80": primary_high_share >= FLOORS["primary_high_share"],
        "definition_outranks_reference": all_outranks,
    }

    return {
        "corpus": corpus,
        "summary": {
            "num_cases": len(cases),
            "band_relevance_agreement": band_relevance_agreement,
            "high_band_precision": high_band_precision,
            "high_band_recall": high_band_recall,
            "primary_high_share": primary_high_share,
            "definition_outranks_reference": all_outranks,
            "targets_met": targets_met,
            "baseline": {
                "band_relevance_agreement": baseline_band_relevance_agreement,
                "high_band_precision": baseline_high_band_precision,
            },
        },
        "cases": report_cases,
    }


def build_fixture_components(
    work_dir: Path, fixtures: tuple[str, ...] = DEFAULT_FIXTURES
) -> dict[str, Any]:
    """Copy *fixtures* into a combined corpus under *work_dir* and index it."""
    repo = work_dir / "combined"
    repo.mkdir(parents=True, exist_ok=True)
    for name in fixtures:
        shutil.copytree(FIXTURES_DIR / name, repo / name)
    return _indexed_components(repo, repo / ".context")


def format_report(report: dict[str, Any]) -> str:
    """Render the human-readable summary table for *report*."""
    summary = report["summary"]
    baseline = summary["baseline"]
    lines = [
        "=" * 60,
        "Confidence Calibration Evaluation",
        f"Corpus: {report['corpus']}",
        "=" * 60,
        f"Cases: {summary['num_cases']}",
        f"Band-relevance agreement : {summary['band_relevance_agreement']:.2f}"
        f"   (baseline {baseline['band_relevance_agreement']:.2f})",
        f"High-band precision      : {summary['high_band_precision']:.2f}"
        f"   (floor {FLOORS['high_band_precision']:.2f},"
        f" baseline {baseline['high_band_precision']:.2f})",
        f"High-band recall         : {summary['high_band_recall']:.2f}"
        f"   (floor {FLOORS['high_band_recall']:.2f})",
        f"Primary high share       : {summary['primary_high_share']:.2f}"
        f"   (floor {FLOORS['primary_high_share']:.2f})",
        "Definition > reference   : "
        + ("PASS" if summary["definition_outranks_reference"] else "FAIL"),
        "-" * 60,
        "TARGETS: " + ("ALL PASS" if all(summary["targets_met"].values()) else "FAILED"),
        "=" * 60,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: build a corpus, evaluate, and print/emit the report."""
    parser = argparse.ArgumentParser(description="Evaluate confidence calibration")
    parser.add_argument("--repo", type=Path, default=None, help="External repo to index")
    parser.add_argument("--output", type=Path, default=None, help="Write report JSON here")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    if args.repo is not None:
        repo = args.repo.resolve()
        components = _indexed_components(repo, repo / ".context")
        corpus = str(repo)
        report = evaluate(components, limit=args.limit, corpus=corpus)
    else:
        with tempfile.TemporaryDirectory(prefix="confidence_eval_") as tmp:
            components = build_fixture_components(Path(tmp))
            report = evaluate(components, limit=args.limit)

    print(format_report(report))
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
