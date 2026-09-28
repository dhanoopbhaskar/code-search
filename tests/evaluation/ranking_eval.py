#!/usr/bin/env python3
"""Deterministic ranking evaluation harness for the match-boost layer.

Indexes the hermetic ``relevance`` fixture, runs the labelled ground-truth
queries, and reports exact-filename top-1/top-3, exact-symbol top-1/top-3,
definition-above-reference, precision at 5, and MRR at 10. The same metrics are
computed with the match-boost layer disabled (``baseline``) so the delta against
the pre-change path is visible.

The harness is importable: ``tests/integration/test_ranking_eval_gate.py``
calls :func:`evaluate` to enforce the CI floors without re-implementing the
metrics. Run standalone with::

    python tests/evaluation/ranking_eval.py
    python tests/evaluation/ranking_eval.py --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import FIXTURES_DIR, _indexed_components
from tests.evaluation.ranking_ground_truth import (
    GROUND_TRUTH_CASES,
    RESOLUTION_CASES,
    RankingCase,
    ResolutionCase,
)

DEFAULT_FIXTURE = "relevance"
DEFAULT_LIMIT = 10
CORPUS_LABEL = "relevance fixture"

#: CI metric floors.
FLOORS: dict[str, float] = {
    "exact_filename_top1": 0.90,
    "exact_filename_top3": 1.00,
    "exact_symbol_top1": 0.90,
    "exact_symbol_top3": 1.00,
    "definition_above_reference": 1.00,
}

#: CI floors for the partial-name resolution metrics.
RESOLUTION_FLOORS: dict[str, float] = {
    "partial_resolution_top1": 0.90,
    "overload_primary_top1": 0.85,
    "overload_order_match": 0.85,
}

#: Fixtures the labelled resolution cases are drawn from.
RESOLUTION_FIXTURES: tuple[str, ...] = (
    "transparency",
    "overload_symbols",
    "deprecated_symbols",
)


@dataclass(frozen=True)
class RankingMetrics:
    """Aggregate metrics computed against the labelled set.

    All fractions are in ``[0.0, 1.0]``.
    """

    exact_filename_top1: float = 0.0
    exact_filename_top3: float = 0.0
    exact_symbol_top1: float = 0.0
    exact_symbol_top3: float = 0.0
    definition_above_reference: float = 1.0
    precision_at_5: float = 0.0
    mrr_at_10: float = 0.0

    def as_dict(self) -> dict[str, float]:
        """Return the metrics as a JSON-serializable mapping."""
        return {
            "exact_filename_top1": self.exact_filename_top1,
            "exact_filename_top3": self.exact_filename_top3,
            "exact_symbol_top1": self.exact_symbol_top1,
            "exact_symbol_top3": self.exact_symbol_top3,
            "definition_above_reference": self.definition_above_reference,
            "precision_at_5": self.precision_at_5,
            "mrr_at_10": self.mrr_at_10,
        }


def _short_symbol_name(fqn: str) -> str:
    """Return the trailing symbol name of *fqn* (call signature stripped)."""
    normalized = fqn.split("(", 1)[0]
    if "::" in normalized:
        normalized = normalized.rsplit("::", 1)[-1]
    return normalized.rsplit(".", 1)[-1]


def _matches_expected(result: dict[str, Any], case: RankingCase) -> bool:
    """Return whether *result* is the labelled expected result for *case*."""
    if case.expected_file not in result.get("file_path", ""):
        return False
    if case.expected_fqn:
        return case.expected_fqn in result.get("fqn", "")
    return True


def _rank(results: list[dict[str, Any]], case: RankingCase) -> int | None:
    """Return the 1-based rank of the expected result, or ``None`` when absent."""
    for index, result in enumerate(results, start=1):
        if _matches_expected(result, case):
            return index
    return None


def _definition_outranks_reference(results: list[dict[str, Any]]) -> bool:
    """Return whether every definition outranks a same-named reference.

    Groups by short symbol name; when a group holds both a definition and a
    reference, the best definition must rank above the best reference.
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_name.setdefault(_short_symbol_name(result.get("fqn", "")), []).append(result)
    for group in by_name.values():
        definitions = [i for i, r in enumerate(group) if r.get("role") == "definition"]
        references = [i for i, r in enumerate(group) if r.get("role") == "reference"]
        if definitions and references and min(definitions) > min(references):
            return False
    return True


def _precision_at_5(results: list[dict[str, Any]], case: RankingCase) -> float:
    """Return the relevant fraction in the top 5 for *case* (fixed denominator)."""
    top5 = results[:5]
    relevant = sum(1 for result in top5 if _matches_expected(result, case))
    return relevant / 5.0


def _reciprocal_rank(results: list[dict[str, Any]], case: RankingCase) -> float:
    """Return the reciprocal rank of the first expected result within top 10."""
    for index, result in enumerate(results[:10], start=1):
        if _matches_expected(result, case):
            return 1.0 / index
    return 0.0


def _compute_metrics(
    search: Any, cases: tuple[RankingCase, ...], limit: int
) -> tuple[RankingMetrics, list[dict[str, Any]]]:
    """Run *cases* through *search* and aggregate the metrics.

    Returns the aggregate metrics and the per-case failure descriptors.
    """
    filename_total = 0
    filename_top1 = 0
    filename_top3 = 0
    symbol_total = 0
    symbol_top1 = 0
    symbol_top3 = 0
    definition_above_reference = True
    precision_sum = 0.0
    mrr_sum = 0.0
    failures: list[dict[str, Any]] = []

    for case in cases:
        if case.content_scope:
            envelope = search.search(case.query, limit=limit, content=case.content_scope)
        else:
            envelope = search.search(case.query, limit=limit)
        results = envelope["results"]
        rank = _rank(results, case)
        precision_sum += _precision_at_5(results, case)
        mrr_sum += _reciprocal_rank(results, case)

        if case.category == "symbol" and not _definition_outranks_reference(results):
            definition_above_reference = False

        if case.category == "filename":
            filename_total += 1
            if rank == 1:
                filename_top1 += 1
            if rank is not None and rank <= 3:
                filename_top3 += 1
        elif case.category == "symbol":
            symbol_total += 1
            if rank == 1:
                symbol_top1 += 1
            if rank is not None and rank <= 3:
                symbol_top3 += 1

        if rank is None or rank > case.top_k:
            reason = "expected result absent" if rank is None else f"rank {rank} > {case.top_k}"
            failures.append(
                {
                    "query": case.query,
                    "category": case.category,
                    "expected": case.expected_fqn or case.expected_file,
                    "rank": rank,
                    "reason": reason,
                }
            )

    metrics = RankingMetrics(
        exact_filename_top1=filename_top1 / filename_total if filename_total else 0.0,
        exact_filename_top3=filename_top3 / filename_total if filename_total else 0.0,
        exact_symbol_top1=symbol_top1 / symbol_total if symbol_total else 0.0,
        exact_symbol_top3=symbol_top3 / symbol_total if symbol_total else 0.0,
        definition_above_reference=definition_above_reference,
        precision_at_5=precision_sum / len(cases) if cases else 0.0,
        mrr_at_10=mrr_sum / len(cases) if cases else 0.0,
    )
    return metrics, failures


def evaluate(
    components: dict[str, Any],
    cases: tuple[RankingCase, ...] = GROUND_TRUTH_CASES,
    limit: int = DEFAULT_LIMIT,
    corpus: str = CORPUS_LABEL,
) -> dict[str, Any]:
    """Run the labelled queries and compute the ranking metrics.

    Args:
        components: Indexed components (from ``_indexed_components``).
        cases: The labelled ranking cases.
        limit: Results per query.
        corpus: Corpus label echoed into the report.

    Returns:
        The ranking report (``corpus``, ``limit``, ``cases``, ``metrics``,
        ``baseline``, ``failures``).
    """
    from src.engine.search import HybridSearch

    search = components["search"]
    metrics, failures = _compute_metrics(search, cases, limit)

    baseline_settings = replace(components["settings"], match_boost_enabled=False)
    baseline_search = HybridSearch(
        components["db"],
        components["vector_index"],
        components["embedding_gen"],
        baseline_settings,
    )
    baseline, _ = _compute_metrics(baseline_search, cases, limit)

    return {
        "corpus": corpus,
        "limit": limit,
        "cases": len(cases),
        "metrics": metrics.as_dict(),
        "baseline": baseline.as_dict(),
        "failures": failures,
    }


def build_fixture_components(work_dir: Path, fixture: str = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Copy *fixture* into *work_dir* and index it with prose on."""
    repo = work_dir / "relevance_repo"
    shutil.copytree(FIXTURES_DIR / fixture, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def build_resolution_components(work_dir: Path) -> dict[str, dict[str, Any]]:
    """Index each resolution fixture once, keyed by fixture name."""
    components: dict[str, dict[str, Any]] = {}
    for fixture in RESOLUTION_FIXTURES:
        repo = work_dir / fixture
        shutil.copytree(FIXTURES_DIR / fixture, repo)
        components[fixture] = _indexed_components(
            repo, repo / ".context", settings_kwargs={"index_prose": True}
        )
    return components


def _legacy_resolution(case: ResolutionCase, components: dict[str, Any]) -> tuple[str, Any, list]:
    """Approximate the pre-change resolution rule for baseline comparison.

    Mirrors the removed ``_rank_symbol_candidates`` behaviour: exact FQN /
    conventional FQN / unique bare leaf resolve; a parent-qualified name
    auto-selects the first storage-ordered match; anything else is a ranked
    storage-ordered list.
    """
    from src.engine.graph import (
        _resolve_symbol_candidates,
        _strip_params,
        _symbol_leaf,
    )
    from src.engine.symbols import _attach_row_signature

    with components["db"].connect() as conn:
        candidates = [
            _attach_row_signature(c) for c in _resolve_symbol_candidates(conn, case.query)
        ]
    for row in candidates:
        if row.get("fqn") == case.query or row.get("conventional_fqn") == case.query:
            return "exact", row, []
    leaf = _symbol_leaf(case.query)
    name_rows = [row for row in candidates if row.get("name") == leaf]
    if not name_rows:
        return "suggestion", None, candidates[:10]
    if len(name_rows) == 1:
        return "exact", name_rows[0], []
    if "." in case.query:
        prefix = _strip_params(case.query.rsplit(".", 1)[0])
        for row in name_rows:
            parent_name = row.get("parent_name")
            if parent_name and (parent_name == prefix or prefix.endswith("." + parent_name)):
                return "exact", row, []
    return "ambiguous", None, name_rows


def _score_resolution(
    case: ResolutionCase,
    kind: str,
    symbol: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> tuple[bool, bool, bool]:
    """Return ``(primary_hit, order_hit, resolved_hit)`` for one case."""
    primary_hit = False
    order_hit = False
    resolved_hit = False
    if case.category == "partial":
        if kind == "exact" and symbol and case.expected_primary in (symbol.get("fqn") or ""):
            primary_hit = resolved_hit = True
    else:
        if kind == "ambiguous" and candidates:
            top = candidates[0].get("fqn") or ""
            primary_hit = case.expected_primary in top
        if case.expected_order:
            got = [c.get("fqn") or "" for c in candidates]
            order_hit = len(got) == len(case.expected_order) and all(
                expected in actual
                for expected, actual in zip(case.expected_order, got, strict=True)
            )
        else:
            order_hit = primary_hit
    return primary_hit, order_hit, resolved_hit


def _resolution_metrics(
    components_by_fixture: dict[str, dict[str, Any]],
    cases: tuple[ResolutionCase, ...],
    *,
    legacy: bool,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Compute the partial/overload resolution metrics (or their baseline)."""
    partial_total = partial_hit = 0
    overload_total = overload_hit = overload_order_hit = 0
    failures: list[dict[str, Any]] = []
    for case in cases:
        components = components_by_fixture[case.fixture]
        if legacy:
            kind, symbol, candidates = _legacy_resolution(case, components)
        else:
            envelope = components["symbol_store"].resolve_name(case.query)
            kind = envelope["kind"]
            symbol = envelope.get("symbol")
            candidates = envelope.get("candidates") or []
        primary_hit, order_hit, resolved_hit = _score_resolution(case, kind, symbol, candidates)
        if case.category == "partial":
            partial_total += 1
            if resolved_hit:
                partial_hit += 1
            else:
                failures.append(
                    {
                        "query": case.query,
                        "category": case.category,
                        "expected": case.expected_primary,
                        "reason": f"kind={kind}",
                    }
                )
        else:
            overload_total += 1
            if primary_hit:
                overload_hit += 1
            else:
                failures.append(
                    {
                        "query": case.query,
                        "category": case.category,
                        "expected": case.expected_primary,
                        "reason": "primary candidate not top-ranked",
                    }
                )
            if order_hit:
                overload_order_hit += 1
            else:
                failures.append(
                    {
                        "query": case.query,
                        "category": "overload_order",
                        "expected": list(case.expected_order),
                        "reason": "candidate order mismatch",
                    }
                )
    metrics = {
        "partial_resolution_top1": partial_hit / partial_total if partial_total else 0.0,
        "overload_primary_top1": overload_hit / overload_total if overload_total else 0.0,
        "overload_order_match": overload_order_hit / overload_total if overload_total else 0.0,
    }
    return metrics, failures


def evaluate_resolution(
    components_by_fixture: dict[str, dict[str, Any]],
    cases: tuple[ResolutionCase, ...] = RESOLUTION_CASES,
) -> dict[str, Any]:
    """Run the labelled resolution cases and compute the resolution metrics.

    Returns the resolution report (``cases``, ``metrics``, ``baseline``,
    ``floors``, ``failures``) where ``baseline`` is the pre-change resolution
    rule applied to the same labelled set.
    """
    metrics, failures = _resolution_metrics(components_by_fixture, cases, legacy=False)
    baseline, _ = _resolution_metrics(components_by_fixture, cases, legacy=True)
    return {
        "cases": len(cases),
        "metrics": metrics,
        "baseline": baseline,
        "floors": dict(RESOLUTION_FLOORS),
        "failures": failures,
    }


def format_report(report: dict[str, Any]) -> str:
    """Render the human-readable summary table for *report*."""
    metrics = report["metrics"]
    baseline = report["baseline"]
    lines = [
        "=" * 60,
        "Ranking Evaluation",
        f"Corpus: {report['corpus']}",
        "=" * 60,
        f"Cases: {report['cases']}",
        f"exact-filename top-1 : {metrics['exact_filename_top1']:.2f}"
        f"   (floor {FLOORS['exact_filename_top1']:.2f})",
        f"exact-filename top-3 : {metrics['exact_filename_top3']:.2f}"
        f"   (floor {FLOORS['exact_filename_top3']:.2f})",
        f"exact-symbol top-1   : {metrics['exact_symbol_top1']:.2f}"
        f"   (floor {FLOORS['exact_symbol_top1']:.2f})",
        f"exact-symbol top-3   : {metrics['exact_symbol_top3']:.2f}"
        f"   (floor {FLOORS['exact_symbol_top3']:.2f})",
        f"def > reference      : {metrics['definition_above_reference']:.2f}"
        f"   (floor {FLOORS['definition_above_reference']:.2f})",
        f"P@5                  : {metrics['precision_at_5']:.2f}"
        f"   (baseline {baseline['precision_at_5']:.2f})",
        f"MRR@10               : {metrics['mrr_at_10']:.2f}"
        f"   (baseline {baseline['mrr_at_10']:.2f})",
        "=" * 60,
    ]
    if report["failures"]:
        lines.append("Failures:")
        for failure in report["failures"]:
            lines.append(
                f"  {failure['category']}: {failure['query']!r} -> {failure['expected']}"
                f" ({failure['reason']})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: build a corpus, evaluate, and print/emit the report."""
    parser = argparse.ArgumentParser(description="Evaluate filename/exact-match ranking")
    parser.add_argument("--repo", type=Path, default=None, help="External repo to index")
    parser.add_argument("--output", type=Path, default=None, help="Write report JSON here")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    if args.repo is not None:
        repo = args.repo.resolve()
        components = _indexed_components(repo, repo / ".context")
        report = evaluate(components, limit=args.limit, corpus=str(repo))
    else:
        with tempfile.TemporaryDirectory(prefix="ranking_eval_") as tmp:
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
