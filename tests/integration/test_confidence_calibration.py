"""Integration tests for confidence score calibration.

Runs the real engine over a combined corpus of the ``quality_defects`` and
``relevance`` fixtures and asserts the calibrated confidence bands, the
ranking-independence invariant, the ground-truth CI gate, and the degraded
lexical-only path.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.engine.search import HybridSearch
from tests.evaluation.confidence_calibration_eval import (
    FLOORS,
    build_fixture_components,
    evaluate,
)
from tests.evaluation.confidence_ground_truth import GROUND_TRUTH_CASES


@pytest.fixture(scope="module")
def calibration_components(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Index the combined ground-truth corpus once for the module."""
    work = tmp_path_factory.mktemp("confidence_calibration")
    return build_fixture_components(work)


def _results(components: dict[str, Any], query: str, limit: int = 10) -> list[dict[str, Any]]:
    return components["search"].search(query, limit=limit)["results"]


@pytest.mark.integration
class TestUS1PrimaryDefinitions:
    """Obvious primary definitions are reported high, not borderline."""

    def test_reported_auth_case_is_high(self, calibration_components: dict[str, Any]) -> None:
        results = _results(calibration_components, "AuthController.authenticate")
        assert results, "the auth controller query must return results"
        top = results[0]
        assert "auth/AuthController.java" in top["file_path"], top["file_path"]
        assert top["confidence_band"] == "high", top
        assert top["confidence"] >= 0.8, top
        assert top["borderline"] is False

    def test_fixture_controller_endpoint_is_high(
        self, calibration_components: dict[str, Any]
    ) -> None:
        results = _results(calibration_components, "ArticleController.getArticle")
        assert results
        top = results[0]
        assert "article/ArticleController.java" in top["file_path"], top["file_path"]
        assert top["confidence_band"] == "high", top
        assert top["confidence"] >= 0.8, top
        assert top["borderline"] is False

    def test_confidence_does_not_change_ranking(
        self, calibration_components: dict[str, Any]
    ) -> None:
        """Confidence is report-only: a high result may rank below a medium one."""
        results = _results(calibration_components, "ArticleService.createComment")
        confidences = [r["confidence"] for r in results]
        assert confidences != sorted(confidences, reverse=True), (
            "confidence must not be the ranking key"
        )
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "order must follow the fused score"


@pytest.mark.integration
class TestUS2ExactMatches:
    """Exact FQN/symbol matches are recognized; fuzzy ones are not."""

    def test_exact_fqn_query_is_high(self, calibration_components: dict[str, Any]) -> None:
        results = _results(calibration_components, "ArticleRepository.findById")
        expected = [r for r in results if "ArticleRepository.java" in r["file_path"]]
        assert expected, "the exact-FQN definition must be returned"
        assert expected[0]["confidence_band"] == "high", expected[0]

    def test_exact_symbol_query_at_least_medium(
        self, calibration_components: dict[str, Any]
    ) -> None:
        results = _results(calibration_components, "AuthService")
        assert results
        top = results[0]
        assert "auth/AuthService.java" in top["file_path"], top["file_path"]
        assert top["confidence_band"] in ("high", "medium"), top
        assert top["confidence"] >= 0.7, top

    def test_fuzzy_paraphrase_gets_no_exact_floor(
        self, calibration_components: dict[str, Any]
    ) -> None:
        results = _results(calibration_components, "validate login credentials")
        assert all(r["confidence_band"] != "high" for r in results), results


@pytest.mark.integration
class TestUS3DefinitionsOutrankReferences:
    """Definitions and controller endpoints outrank references."""

    def test_controller_endpoint_definition_is_high(
        self, calibration_components: dict[str, Any]
    ) -> None:
        results = _results(calibration_components, "ArticleController.getArticle")
        assert results
        assert results[0]["role"] == "definition"
        assert results[0]["confidence_band"] == "high"

    @pytest.mark.parametrize(
        "query",
        [
            "AuthService.authenticate",
            "ArticleController.getArticle",
            "ArticleService.deleteArticle",
        ],
    )
    def test_definition_outranks_every_reference(
        self, calibration_components: dict[str, Any], query: str
    ) -> None:
        results = _results(calibration_components, query)
        definitions = [r["confidence"] for r in results if r["role"] == "definition"]
        references = [r["confidence"] for r in results if r["role"] == "reference"]
        if definitions and references:
            assert max(definitions) > max(references), results


@pytest.mark.integration
class TestUS4CalibrationGate:
    """The ground-truth metrics meet their floors and are deterministic."""

    def test_metric_floors(self, calibration_components: dict[str, Any]) -> None:
        summary = evaluate(calibration_components)["summary"]
        assert summary["high_band_precision"] >= FLOORS["high_band_precision"], summary
        assert summary["high_band_recall"] >= FLOORS["high_band_recall"], summary
        assert summary["primary_high_share"] >= FLOORS["primary_high_share"], summary
        assert summary["definition_outranks_reference"] is True, summary
        assert all(summary["targets_met"].values()), summary

    def test_baseline_improvement_and_precision(
        self, calibration_components: dict[str, Any]
    ) -> None:
        summary = evaluate(calibration_components)["summary"]
        baseline = summary["baseline"]
        assert summary["band_relevance_agreement"] - baseline["band_relevance_agreement"] >= 0.30, (
            summary
        )
        assert summary["high_band_precision"] >= baseline["high_band_precision"], summary

    def test_metrics_are_deterministic(self, calibration_components: dict[str, Any]) -> None:
        first = evaluate(calibration_components)
        second = evaluate(calibration_components)
        assert first["summary"] == second["summary"]
        assert first["cases"] == second["cases"]

    def test_per_result_output_is_byte_identical(
        self, calibration_components: dict[str, Any]
    ) -> None:
        def fingerprint(rs: list[dict[str, Any]]) -> list[tuple[int, float, str]]:
            return [(r["chunk_id"], r["confidence"], r["confidence_band"]) for r in rs]

        for case in GROUND_TRUTH_CASES:
            first = _results(calibration_components, case.query)
            second = _results(calibration_components, case.query)
            assert fingerprint(first) == fingerprint(second), case.query


@pytest.mark.integration
class TestDegradedLexicalPath:
    """Confidence stays meaningful when the vector arm is disabled."""

    def test_exact_definitions_high_without_vector(
        self, calibration_components: dict[str, Any]
    ) -> None:
        degraded = HybridSearch(
            calibration_components["db"],
            calibration_components["vector_index"],
            calibration_components["embedding_gen"],
            calibration_components["settings"],
            no_model=True,
        )
        env = degraded.search("AuthController.authenticate", limit=10)
        assert env["results"]
        top = env["results"][0]
        assert top["vector_score"] == 0.0
        assert top["confidence_band"] == "high", top

    def test_weak_lexical_matches_stay_below_high(
        self, calibration_components: dict[str, Any]
    ) -> None:
        degraded = HybridSearch(
            calibration_components["db"],
            calibration_components["vector_index"],
            calibration_components["embedding_gen"],
            calibration_components["settings"],
            no_model=True,
        )
        results = degraded.search("validate login credentials", limit=10)["results"]
        assert all(r["confidence_band"] != "high" for r in results), results
