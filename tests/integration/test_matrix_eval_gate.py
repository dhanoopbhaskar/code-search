"""Gate and determinism checks for the cross-repository baseline harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.evaluation.matrix_eval import run_matrix
from tests.evaluation.matrix_ground_truth import (
    CATEGORIES,
    MATRIX_QUERIES,
    MATRIX_REPOS,
    active_repos,
)


def test_labels_use_known_categories_and_repositories() -> None:
    """Every query belongs to a known repository and category."""
    repo_ids = {repo.id for repo in MATRIX_REPOS}
    for query in MATRIX_QUERIES:
        assert query.repo_id in repo_ids
        assert query.category in CATEGORIES
        if query.expect_weak:
            assert query.expected_files == ()
            assert query.category == "negative"
        else:
            assert query.expected_files or query.grades


def test_active_repositories_have_labelled_queries() -> None:
    """Every measured repository carries at least one query."""
    for repo in active_repos():
        if repo.tier == "unsupported":
            continue
        assert any(query.repo_id == repo.id for query in MATRIX_QUERIES), repo.id


def test_matrix_report_has_required_metrics(tmp_path: Path) -> None:
    """The report exposes ranking, composition, latency, size, and edge counts."""
    report = run_matrix(tmp_path)
    measured_ids = {repo["id"] for repo in report["repos"]}
    assert measured_ids == {repo.id for repo in active_repos()}
    assert {item["id"] for item in report["pending"]} == {
        repo.id for repo in MATRIX_REPOS if repo.pending
    }

    required_repo_metrics = {
        "queries",
        "ndcg_at_10",
        "top1",
        "top3",
        "negative_weak_rate",
        "production_results",
        "test_results",
        "first_query_latency_ms",
        "warm_latency_p50_ms",
    }
    required_index_metrics = {
        "index_build_ms",
        "chunks",
        "symbols",
        "edges_resolved",
        "edges_unresolved",
        "size_bytes_total",
        "edge_precision",
    }
    required_query_metrics = {
        "query",
        "category",
        "rank",
        "passed",
        "ndcg_at_10",
        "latency_ms",
        "weak",
        "production_results",
        "test_results",
        "content_composition",
        "response_chars",
        "response_tokens_estimated",
    }
    for repo in report["repos"]:
        assert required_repo_metrics <= set(repo["metrics"])
        assert required_index_metrics <= set(repo["index"])
        for record in repo["queries"]:
            assert required_query_metrics <= set(record)

    assert "ndcg_at_10" in report["aggregate"]
    assert "production_share" in report["aggregate"]
    assert "content_composition" in report["aggregate"]


def test_unsupported_languages_are_skipped(tmp_path: Path) -> None:
    """Scala, Dart, HTML, and Protobuf files are not discovered or indexed."""
    report = run_matrix(tmp_path)
    unsupported = next(repo for repo in report["repos"] if repo["id"] == "unsupported-languages")
    assert unsupported["discovered_files"] == 0
    assert unsupported["index"]["chunks"] == 0


def _stable_queries(report: dict[str, Any], repo_id: str) -> list[tuple[Any, ...]]:
    """Return the query outcomes that must be identical across runs."""
    repo = next(item for item in report["repos"] if item["id"] == repo_id)
    return [
        (
            record["query"],
            record["rank"],
            record["ndcg_at_10"],
            record["weak"],
            record["production_results"],
            record["test_results"],
            record["content_composition"],
        )
        for record in repo["queries"]
    ]


@pytest.mark.parametrize("repo_id", ["java-docs", "typescript-react"])
def test_matrix_outcomes_are_deterministic(tmp_path: Path, repo_id: str) -> None:
    """Two runs over the same fixture produce the same ranked outcomes."""
    repo = next(item for item in active_repos() if item.id == repo_id)
    first = run_matrix(tmp_path / "first", repos=(repo,))
    second = run_matrix(tmp_path / "second", repos=(repo,))
    assert _stable_queries(first, repo_id) == _stable_queries(second, repo_id)
