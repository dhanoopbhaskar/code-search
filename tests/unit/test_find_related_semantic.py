"""Unit tests for find_related semantic relevance signals."""

from __future__ import annotations

import pytest

from src.engine.semantic_signals import (
    RelevanceScore,
    SemanticSignals,
    _is_structural_false_positive,
    compute_final_score,
    compute_package_overlap,
    compute_semantic_score,
    compute_type_sharing,
)


class TestComputePackageOverlap:
    """Tests for package overlap computation."""

    def test_same_package_returns_one(self):
        anchor = "/project/src/com/example/service/ArticleService.java"
        candidate = "/project/src/com/example/service/ArticleRepository.java"
        assert compute_package_overlap(anchor, candidate) == 1.0

    def test_shared_parent_package_returns_partial(self):
        anchor = "/project/src/com/example/service/ArticleService.java"
        candidate = "/project/src/com/example/repository/ArticleRepository.java"
        # Shared: com, example | Union: com, example, service, repository
        score = compute_package_overlap(anchor, candidate)
        assert 0.0 < score < 1.0

    def test_completely_different_packages_returns_zero(self):
        # Packages in unrelated namespaces score 0.0 even when their
        # absolute paths share repo scaffolding (project/src).
        anchor = "/project/src/com/example/service/ArticleService.java"
        candidate = "/project/src/org/other/module/Something.java"
        score = compute_package_overlap(anchor, candidate)
        # Namespace segments (com,example,service) vs (org,other,module) share nothing.
        assert score == 0.0

    def test_no_shared_segments_returns_zero(self):
        anchor = "/a/b/c/ArticleService.java"
        candidate = "/x/y/z/Something.java"
        score = compute_package_overlap(anchor, candidate)
        assert score == 0.0

    def test_same_file_returns_one(self):
        anchor = "/project/src/com/example/ArticleService.java"
        candidate = "/project/src/com/example/ArticleService.java"
        assert compute_package_overlap(anchor, candidate) == 1.0

    def test_root_level_files(self):
        anchor = "/project/FileA.java"
        candidate = "/project/FileB.java"
        assert compute_package_overlap(anchor, candidate) == 1.0

    def test_empty_paths(self):
        assert compute_package_overlap("", "") == 1.0
        assert compute_package_overlap("/a/b.java", "") == 0.0
        assert compute_package_overlap("", "/a/b.java") == 0.0


class TestComputeTypeSharing:
    """Tests for type sharing computation."""

    def test_no_signature_returns_zero(self):
        anchor = "com.example.ArticleService"
        candidate = "com.example.ArticleRepository"
        assert compute_type_sharing(anchor, candidate) == 0.0

    def test_shared_param_types(self):
        anchor = "com.example.ArticleService.save(Article,User)"
        candidate = "com.example.ArticleRepository.save(Article,User)"
        score = compute_type_sharing(anchor, candidate)
        assert score > 0.5

    def test_partial_type_overlap(self):
        anchor = "com.example.ArticleService.save(Article,User,String)"
        candidate = "com.example.ArticleRepository.save(Article,User)"
        score = compute_type_sharing(anchor, candidate)
        assert 0.0 < score < 1.0

    def test_no_shared_types(self):
        anchor = "com.example.Service.process(String,Integer)"
        candidate = "com.example.Repository.find(Long,Boolean)"
        score = compute_type_sharing(anchor, candidate)
        assert score == 0.0

    def test_generics_erased(self):
        anchor = "com.example.Service.save(List<Article>,Map<String,Object>)"
        candidate = "com.example.Repository.save(List<Article>,Map<String,Object>)"
        score = compute_type_sharing(anchor, candidate)
        assert score == 1.0

    def test_return_type_not_parsed(self):
        # normalize_signature only extracts parameter types, not return types
        anchor = "com.example.Service.find(Article)->Article"
        candidate = "com.example.Repository.find(Article)->Article"
        score = compute_type_sharing(anchor, candidate)
        # Only parameter types are compared, return type is ignored
        assert score == 1.0  # Same param types


class TestSemanticSignals:
    """Tests for SemanticSignals dataclass."""

    def test_valid_signals(self):
        signals = SemanticSignals(0.5, 0.3, 0.8)
        assert signals.package_overlap == 0.5
        assert signals.type_sharing == 0.3
        assert signals.call_proximity == 0.8

    def test_invalid_package_overlap_raises(self):
        with pytest.raises(ValueError):
            SemanticSignals(1.5, 0.3, 0.8)

    def test_invalid_type_sharing_raises(self):
        with pytest.raises(ValueError):
            SemanticSignals(0.5, -0.1, 0.8)

    def test_invalid_call_proximity_raises(self):
        with pytest.raises(ValueError):
            SemanticSignals(0.5, 0.3, 1.5)


class TestRelevanceScore:
    """Tests for RelevanceScore dataclass."""

    def test_valid_scores(self):
        score = RelevanceScore(0.6, 0.7, 0.65)
        assert score.semantic_score == 0.6
        assert score.vector_score == 0.7
        assert score.final_score == 0.65

    def test_invalid_final_score_raises(self):
        with pytest.raises(ValueError):
            RelevanceScore(0.6, 0.7, 1.5)


class TestComputeSemanticScore:
    """Tests for combined semantic score computation."""

    def test_combines_all_three_signals(self):
        anchor = {
            "fqn": "com.example.ArticleService.save(Article)",
            "file_path": "/a/b/ArticleService.java",
            "symbol_id": 1,
        }
        candidate = {
            "fqn": "com.example.ArticleRepository.save(Article)",
            "file_path": "/a/b/ArticleRepository.java",
            "symbol_id": 2,
        }

        # Mock database - we'll just test the signal computation without DB
        class MockDB:
            def connect(self):
                class MockConn:
                    def execute(self, *args, **kwargs):
                        return []

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        pass

                return MockConn()

        signals = compute_semantic_score(anchor, candidate, MockDB())

        assert isinstance(signals, SemanticSignals)
        assert 0.0 <= signals.package_overlap <= 1.0
        assert 0.0 <= signals.type_sharing <= 1.0
        assert 0.0 <= signals.call_proximity <= 1.0


class TestComputeFinalScore:
    """Tests for final relevance score computation."""

    def test_pure_vector_when_alpha_zero(self):
        signals = SemanticSignals(0.5, 0.5, 0.5)
        weights = {"package": 0.3, "type": 0.3, "call_graph": 0.4}
        score = compute_final_score(signals, 0.8, weights, 0.0)
        assert score.final_score == 0.8
        assert score.vector_score == 0.8

    def test_pure_semantic_when_alpha_one(self):
        signals = SemanticSignals(0.5, 0.5, 0.5)
        weights = {"package": 0.3, "type": 0.3, "call_graph": 0.4}
        semantic = 0.3 * 0.5 + 0.3 * 0.5 + 0.4 * 0.5  # = 0.5
        score = compute_final_score(signals, 0.8, weights, 1.0)
        assert abs(score.final_score - semantic) < 1e-6

    def test_hybrid_alpha_half(self):
        signals = SemanticSignals(1.0, 1.0, 1.0)  # max semantic
        weights = {"package": 0.3, "type": 0.3, "call_graph": 0.4}
        score = compute_final_score(signals, 0.5, weights, 0.5)
        semantic = 1.0
        expected = 0.5 * semantic + 0.5 * 0.5
        assert abs(score.final_score - expected) < 1e-6


class TestStructuralFalsePositiveDetection:
    """Tests for structural false positive detection."""

    def test_high_vector_low_semantic_is_false_positive(self):
        signals = SemanticSignals(0.0, 0.0, 0.0)  # No semantic relevance
        assert _is_structural_false_positive(signals, 0.8) is True

    def test_high_semantic_not_false_positive(self):
        signals = SemanticSignals(0.5, 0.5, 0.5)  # Good semantic relevance
        assert _is_structural_false_positive(signals, 0.8) is False

    def test_low_vector_not_false_positive(self):
        signals = SemanticSignals(0.0, 0.0, 0.0)
        assert _is_structural_false_positive(signals, 0.5) is False

    def test_threshold_boundary(self):
        signals = SemanticSignals(0.1, 0.1, 0.1)  # Below 0.15 threshold
        assert _is_structural_false_positive(signals, 0.71) is True
        assert _is_structural_false_positive(signals, 0.69) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
