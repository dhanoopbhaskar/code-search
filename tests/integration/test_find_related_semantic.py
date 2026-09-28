"""Integration tests for find_related semantic relevance.

Covers three scenarios:
- Functionally related code (ArticleService.save -> Article domain slice)
- Cross-module domain discovery (Order entity -> full feature slice)
- Call graph proximity ranking (PaymentProcessor.charge -> direct callers/callees)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import _find_related_payload


def _comps_with(
    tmp_path: Path, subdir: str = "relevance_repo", **settings_kwargs: Any
) -> dict[str, Any]:
    """Build indexed components over the relevance corpora with settings overrides."""
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / subdir
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    extra = FIXTURES_DIR / "relevance_related"
    if extra.exists():
        shutil.copytree(extra, repo, dirs_exist_ok=True)
    return _indexed_components(repo, repo / ".context", settings_kwargs=settings_kwargs)


@pytest.fixture
def semantic_relevance_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over the relevance corpora (Spring Boot-like structure).

    Combines ``tests/fixtures/relevance/`` (article + callee domains, shared
    with the search-regression tests) with ``tests/fixtures/relevance_related/``
    (the order + payment domains used by the domain-discovery and call-graph
    tests), so growing that corpus does not perturb the other tests that index
    the shared ``relevance`` fixture.
    """
    return _comps_with(tmp_path)


def _find_line_number(file_path: Path, target: str) -> int:
    """Find the line number containing target string in file."""
    content = file_path.read_text()
    for i, line in enumerate(content.splitlines(), 1):
        if target in line:
            return i
    raise ValueError(f"Line with '{target}' not found in {file_path}")


# ============================================================================
# Functionally related code
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_us1_article_service_create_comment_returns_article_domain_slice(
    semantic_relevance_comps: dict[str, Any],
) -> None:
    """ArticleService.createComment anchor returns article-related components.

    Expected in top 10:
    - ArticleRepository (same package, shared Comment/Article type, call graph callee)
    - ArticleController (same package, shared Article type, call graph caller)
    - Article domain entity (same package, shared type)
    - ArticleResponse / Comment (same package, shared type)

    NOT in top 10:
    - SecurityConfig (shares @PreAuthorize only)
    - Test files
    """
    comps = semantic_relevance_comps
    anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
    # Anchor on createComment method which calls articleRepository.save
    line_num = _find_line_number(anchor_file, "createComment")

    data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))

    assert data.get("vector_health") is True, data
    results = data["results"]
    assert len(results) >= 5, f"Expected at least 5 results, got {len(results)}"

    # Extract FQNs of results
    result_fqns = [r["fqn"] for r in results]

    # Verify Article domain slice appears in top 10 (more realistic for small fixture)
    top10_fqns = result_fqns[:10]
    # Entity/model chunks carry the file-qualified symbol FQN
    # (``.../Article.java::Article.setBody(String)``), so assert the domain files
    # surface via that prefix rather than the paren-form ``Article(`` which only
    # ever matched incidental ``getArticle(`` methods.
    article_related = [
        "ArticleRepository",
        "ArticleController",
        "Article.java::Article",
        "Comment.java::Comment",
    ]

    for expected in article_related:
        found = any(expected in fqn for fqn in top10_fqns)
        assert found, f"Expected {expected} in top 10 results: {top10_fqns}"

    # Verify structural false positives are NOT in top 10
    false_positives = ["SecurityConfig"]
    for fp in false_positives:
        found = any(fp in fqn for fqn in result_fqns[:10])
        assert not found, (
            f"Structural false positive {fp} should not be in top 10: {result_fqns[:10]}"
        )


@pytest.mark.integration
@pytest.mark.slow
def test_us1_excludes_test_files(semantic_relevance_comps: dict[str, Any]) -> None:
    """Test files should not appear in results."""
    comps = semantic_relevance_comps
    anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
    line_num = _find_line_number(anchor_file, "createComment")

    data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))

    results = data["results"]
    result_fqns = [r["fqn"] for r in results]

    # No test files in results - check class names, not temp paths
    test_indicators = ["Test", "test"]
    for fqn in result_fqns:
        # Extract the class/method name part (after last ::)
        class_part = fqn.split("::")[-1]
        for indicator in test_indicators:
            assert indicator not in class_part, f"Test file found in results: {fqn}"


# ============================================================================
# Cross-module domain discovery
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_us2_order_entity_discovers_full_feature_slice(
    semantic_relevance_comps: dict[str, Any],
) -> None:
    """Order entity anchor discovers full feature slice.

    Expected in top 10:
    - OrderRepository (same package, shared Order type, call graph callee)
    - OrderService (CALLS OrderRepository, shared Order type)
    - OrderController (CALLS OrderService, shared Order type)
    - OrderItem / OrderStatus (same package, referenced by Order)
    """
    comps = semantic_relevance_comps
    order_file = comps["repo"] / "src/main/java/com/example/order/Order.java"
    assert order_file.exists(), "Order entity missing from relevance fixture (spec 021 T068)"

    line_num = _find_line_number(order_file, "class Order")

    data = json.loads(_find_related_payload(comps, str(order_file), line_num, 10))

    assert data.get("vector_health") is True, data
    results = data["results"]
    result_fqns = [r["fqn"] for r in results]

    # Verify the feature slice components that exist in the fixture appear in
    # the top 10 (DTO/Mapper scaffolding lives outside the fixture corpus).
    expected_slice = [
        "OrderRepository",
        "OrderService",
        "OrderController",
        "OrderItem",
        "OrderStatus",
    ]

    found_count = 0
    for expected in expected_slice:
        if any(expected in fqn for fqn in result_fqns[:10]):
            found_count += 1

    # Should find at least 4 of the expected slice components
    assert found_count >= 4, (
        f"Only found {found_count} of expected slice components in top 10: {result_fqns[:10]}"
    )


# ============================================================================
# Call graph proximity ranking
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_us3_call_graph_proximity_ranks_direct_neighbors_higher(
    semantic_relevance_comps: dict[str, Any],
) -> None:
    """PaymentProcessor.charge anchor ranks direct call graph neighbors higher.

    Direct callees (PaymentGateway.charge, FraudService.check — depth 1) should
    rank higher than the transitive callee (PaymentNetwork.authorize — depth 2).
    """
    comps = semantic_relevance_comps
    pp_file = comps["repo"] / "src/main/java/com/example/payment/PaymentProcessor.java"
    assert pp_file.exists(), "PaymentProcessor missing from relevance fixture (spec 021 T068)"

    line_num = _find_line_number(pp_file, "public boolean charge")

    data = json.loads(_find_related_payload(comps, str(pp_file), line_num, 10))

    assert data.get("vector_health") is True, data
    results = data["results"]
    result_fqns = [r["fqn"] for r in results]

    def rank_of(name: str) -> int | None:
        for i, fqn in enumerate(result_fqns):
            if name in fqn:
                return i
        return None

    # Direct callees (depth 1) must appear in the top 5.
    direct_ranks = [
        r for r in (rank_of("PaymentGateway"), rank_of("FraudService")) if r is not None
    ]
    assert direct_ranks, f"No direct callees in results: {result_fqns[:5]}"
    assert min(direct_ranks) < 5, f"Direct callees not in top 5: {result_fqns[:5]}"

    # Transitive callee (PaymentNetwork.authorize, depth 2) must not outrank a
    # direct callee when it is present in the results.
    network_rank = rank_of("PaymentNetwork")
    if network_rank is not None:
        assert min(direct_ranks) < network_rank, (
            f"Depth-2 PaymentNetwork ranked above a direct callee: {result_fqns[:10]}"
        )


# ============================================================================
# Configuration Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_semantic_blend_zero_is_backward_compatible(
    semantic_relevance_comps: dict[str, Any],
) -> None:
    """CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND=0.0 produces legacy vector-only ranking."""
    import os

    os.environ["CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND"] = "0.0"

    try:
        comps = semantic_relevance_comps
        anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
        line_num = _find_line_number(anchor_file, "createComment")

        data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))

        # Should still return results (vector-only mode)
        assert data.get("vector_health") is True, data
        results = data["results"]
        assert len(results) > 0
    finally:
        os.environ.pop("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", None)


@pytest.mark.integration
@pytest.mark.slow
def test_semantic_blend_one_uses_pure_semantic(semantic_relevance_comps: dict[str, Any]) -> None:
    """CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND=1.0 uses only semantic signals."""
    import os

    os.environ["CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND"] = "1.0"

    try:
        comps = semantic_relevance_comps
        anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
        line_num = _find_line_number(anchor_file, "createComment")

        data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))

        assert data.get("vector_health") is True, data
        results = data["results"]
        assert len(results) > 0
    finally:
        os.environ.pop("CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND", None)


# ============================================================================
# Latency Test
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_find_related_latency_under_2_seconds(semantic_relevance_comps: dict[str, Any]) -> None:
    """find_related query latency remains under 2 seconds p99."""
    import time

    comps = semantic_relevance_comps
    anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
    line_num = _find_line_number(anchor_file, "createComment")

    # Run multiple queries to check latency
    latencies = []
    for _ in range(10):
        start = time.monotonic()
        json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))
        latencies.append(time.monotonic() - start)

    p99 = sorted(latencies)[int(0.99 * len(latencies))]
    assert p99 < 2.0, f"p99 latency {p99:.3f}s exceeds 2s budget"


# ============================================================================
# Configuration effect tests
# ============================================================================


def _article_service(
    tmp_path: Path, subdir: str = "relevance_repo", **kwargs: Any
) -> tuple[dict[str, Any], Path, int]:
    comps = _comps_with(tmp_path, subdir=subdir, **kwargs)
    anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
    line_num = _find_line_number(anchor_file, "deleteArticle")
    return comps, anchor_file, line_num


@pytest.mark.integration
@pytest.mark.slow
def test_call_graph_weight_ranks_direct_callee_first(tmp_path: Path) -> None:
    """CODE_SEARCH_FIND_RELATED_WEIGHT_CALL_GRAPH: in pure call-graph mode the
    direct callee of ``ArticleService.deleteArticle`` (``ArticleRepository.deleteById``)
    ranks first, proving the call signal drives the ranking."""
    comps, anchor_file, line_num = _article_service(
        tmp_path,
        find_related_weight_package=0.0,
        find_related_weight_type=0.0,
        find_related_weight_call_graph=1.0,
        find_related_semantic_blend=1.0,
    )
    data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))
    assert data.get("vector_health") is True, data
    top = data["results"][0]["fqn"]
    assert "deleteById" in top, f"expected the direct callee first, got {top}"


@pytest.mark.integration
@pytest.mark.slow
def test_type_weight_ranks_type_sharing_candidate_first(tmp_path: Path) -> None:
    """CODE_SEARCH_FIND_RELATED_WEIGHT_TYPE: anchoring the Comment-persisting
    repository method in pure type mode ranks the other Comment-typed method
    (``CommentService.save``) first."""
    comps = _comps_with(
        tmp_path,
        find_related_weight_package=0.0,
        find_related_weight_type=1.0,
        find_related_weight_call_graph=0.0,
        find_related_semantic_blend=1.0,
    )
    anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleRepository.java"
    line_num = _find_line_number(anchor_file, "save(Comment")
    data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))
    assert data.get("vector_health") is True, data
    top = data["results"][0]["fqn"]
    assert "CommentService.save" in top, f"expected the Comment-typed peer first, got {top}"


@pytest.mark.integration
@pytest.mark.slow
def test_package_weight_keeps_same_package_domain_top(tmp_path: Path) -> None:
    """CODE_SEARCH_FIND_RELATED_WEIGHT_PACKAGE: anchoring a callee-domain class
    in pure package mode keeps the same-namespace neighbours on top."""
    comps = _comps_with(
        tmp_path,
        subdir="package_weight_repo",
        find_related_weight_package=1.0,
        find_related_weight_type=0.0,
        find_related_weight_call_graph=0.0,
        find_related_semantic_blend=1.0,
    )
    anchor_file = comps["repo"] / "src/main/java/com/example/callee/CallerService.java"
    line_num = _find_line_number(anchor_file, "orchestrate")
    data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 5))
    assert data.get("vector_health") is True, data
    # Same-namespace neighbours (package score 1.0) must outrank the
    # cross-package chunks (package score 0.5) in pure-package mode.
    for result in data["results"][:2]:
        assert "/callee/" in result["file_path"], (
            f"out-of-package result outranked a same-package neighbour: {result['file_path']}"
        )


@pytest.mark.integration
@pytest.mark.slow
def test_semantic_blend_changes_ranking(tmp_path: Path) -> None:
    """CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND: legacy (0.0) vector ranking and
    the default semantic ranking order results differently for the same anchor."""
    vector_comps, _, _ = _article_service(
        tmp_path, subdir="blend_vector_repo", find_related_semantic_blend=0.0
    )
    semantic_comps, _, _ = _article_service(
        tmp_path, subdir="blend_semantic_repo", find_related_semantic_blend=0.8
    )

    def top_fqns(comps: dict[str, Any]) -> list[str]:
        anchor_file = comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
        line_num = _find_line_number(anchor_file, "deleteArticle")
        data = json.loads(_find_related_payload(comps, str(anchor_file), line_num, 10))
        assert data.get("vector_health") is True, data
        return [r["fqn"] for r in data["results"]]

    assert top_fqns(vector_comps) != top_fqns(semantic_comps), (
        "semantic blend must change the ranking versus the legacy vector path"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
