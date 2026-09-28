"""CI gate over the labelled ranking evaluation.

Fails the build when any metric floor or the pre-change baseline is not met,
and asserts the harness is deterministic across repeated runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.evaluation.ranking_eval import (
    FLOORS,
    RESOLUTION_FLOORS,
    build_fixture_components,
    build_resolution_components,
    evaluate,
    evaluate_resolution,
)
from tests.evaluation.ranking_ground_truth import SPRING_BOOT_MAIN_CASES


@pytest.fixture
def ranking_report(tmp_path: Path) -> dict[str, Any]:
    """Index the hermetic relevance fixture and run the evaluation once."""
    components = build_fixture_components(tmp_path)
    return evaluate(components)


@pytest.fixture
def resolution_report(tmp_path: Path) -> dict[str, Any]:
    """Index the resolution fixtures and run the partial-name evaluation once."""
    components = build_resolution_components(tmp_path)
    return evaluate_resolution(components)


@pytest.fixture
def spring_boot_main_report(tmp_path: Path) -> dict[str, Any]:
    """Index the hermetic Spring Boot fixture and evaluate the entry-point case."""
    components = build_fixture_components(tmp_path, fixture="spring_boot_main")
    return evaluate(components, cases=SPRING_BOOT_MAIN_CASES, corpus="spring_boot_main fixture")


def test_ranking_eval_meets_all_floors(ranking_report: dict[str, Any]) -> None:
    """Every metric floor is met."""
    metrics = ranking_report["metrics"]
    for name, floor in FLOORS.items():
        assert metrics[name] >= floor, f"{name}={metrics[name]} below floor {floor}"


def test_ranking_eval_not_below_baseline(ranking_report: dict[str, Any]) -> None:
    """Overall retrieval accuracy is not below the pre-change baseline."""
    metrics = ranking_report["metrics"]
    baseline = ranking_report["baseline"]
    assert metrics["precision_at_5"] >= baseline["precision_at_5"]
    assert metrics["mrr_at_10"] >= baseline["mrr_at_10"]


def test_ranking_eval_is_deterministic(tmp_path: Path) -> None:
    """Two runs on unchanged inputs produce identical metrics."""
    components = build_fixture_components(tmp_path)
    first = evaluate(components)
    second = evaluate(components)
    assert first["metrics"] == second["metrics"]
    assert first["baseline"] == second["baseline"]


def test_spring_boot_main_application_ranks_entry_point_first(
    spring_boot_main_report: dict[str, Any],
) -> None:
    """`spring boot main application` returns the entry point at rank 1."""
    assert spring_boot_main_report["failures"] == []


def test_resolution_eval_meets_all_floors(resolution_report: dict[str, Any]) -> None:
    """The labelled partial-name metrics meet their floors."""
    metrics = resolution_report["metrics"]
    for name, floor in RESOLUTION_FLOORS.items():
        assert metrics[name] >= floor, f"{name}={metrics[name]} below floor {floor}"
    assert resolution_report["failures"] == [], resolution_report["failures"]


def test_resolution_eval_not_below_baseline(resolution_report: dict[str, Any]) -> None:
    """The ranked disambiguation improves the primary-candidate top-1 rate."""
    metrics = resolution_report["metrics"]
    baseline = resolution_report["baseline"]
    assert metrics["partial_resolution_top1"] >= baseline["partial_resolution_top1"]
    assert metrics["overload_primary_top1"] >= baseline["overload_primary_top1"]
