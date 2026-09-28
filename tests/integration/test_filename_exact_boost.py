"""End-to-end ranking tests for the filename/exact-match boosting layer.

Covers exact-filename, exact-symbol/FQN, proportional path-term, demotion
withholding, the degraded lexical-only path, and determinism.
"""

from __future__ import annotations

from typing import Any

import pytest


def _paths(envelope: dict[str, Any]) -> list[str]:
    return [r["file_path"] for r in envelope["results"]]


def _leaf(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _match_boost(result: dict[str, Any]) -> dict[str, Any] | None:
    return (result.get("score_sources") or {}).get("match_boost")


# --- Exact filename queries ---------------------------------


def test_readme_docs_scope_ranks_named_file_first(indexed_match_boost: dict[str, Any]) -> None:
    """README with the docs scope returns README.md at rank 1."""
    envelope = indexed_match_boost["search"].search("README", limit=5, content="docs")
    results = envelope["results"]
    assert results, "README must not be gated into an empty result"
    assert _leaf(results[0]["file_path"]) == "README.md"
    assert _match_boost(results[0])["tier"] == "exact_filename"


def test_readme_all_scope_ranks_named_file_first(indexed_match_boost: dict[str, Any]) -> None:
    """README under the all-content scope returns README.md first."""
    envelope = indexed_match_boost["search"].search("README", limit=5, content="all")
    assert _leaf(envelope["results"][0]["file_path"]) == "README.md"


def test_readme_no_model_lexical_path(indexed_match_boost: dict[str, Any]) -> None:
    """The filename boost still applies on the degraded lexical path."""
    from src.engine.search import HybridSearch

    components = indexed_match_boost
    degraded = HybridSearch(
        components["db"],
        components["vector_index"],
        components["embedding_gen"],
        components["settings"],
        no_model=True,
    )
    envelope = degraded.search("README", limit=5, content="docs")
    assert envelope["results"]
    assert _leaf(envelope["results"][0]["file_path"]) == "README.md"


def test_unmatched_query_receives_no_filename_boost(
    indexed_match_boost: dict[str, Any],
) -> None:
    """A query matching no filename receives no boost."""
    envelope = indexed_match_boost["search"].search("wqrble token waffle", limit=5)
    assert envelope["results"] == []
    for result in envelope["results"]:
        assert _match_boost(result) is None


def test_generic_stem_is_dampened_to_proportional_tier(
    indexed_match_boost: dict[str, Any],
) -> None:
    """A generic stem (`config`) never earns the exact-filename tier."""
    envelope = indexed_match_boost["search"].search("config", limit=5)
    boosted = [r for r in envelope["results"] if _match_boost(r) is not None]
    assert boosted, "config.py should still receive a dampened proportional boost"
    assert all(_match_boost(r)["tier"] != "exact_filename" for r in boosted)


def test_exact_filename_tier_withheld_from_test_file(
    indexed_match_boost: dict[str, Any],
) -> None:
    """A test file exact-named by the query does not get the exact tier."""
    envelope = indexed_match_boost["search"].search("auth_service_test", limit=6)
    test_results = [
        r for r in envelope["results"] if _leaf(r["file_path"]) == "auth_service_test.py"
    ]
    for result in test_results:
        assert _match_boost(result) is None or _match_boost(result)["tier"] != "exact_filename"


# --- Exact symbol / FQN queries -----------------------------


def test_exact_symbol_query_ranks_definition_first(
    indexed_relevance: dict[str, Any],
) -> None:
    """An exact symbol query returns the definition above references."""
    envelope = indexed_relevance["search"].search("ArticleService", limit=6)
    results = envelope["results"]
    assert results
    assert _leaf(results[0]["file_path"]) == "ArticleService.java"
    assert results[0]["role"] == "definition"
    assert _match_boost(results[0])["tier"] in ("exact_symbol", "exact_filename")


def test_exact_fqn_query_ranks_definition_first(
    indexed_relevance: dict[str, Any],
) -> None:
    """An exact FQN query returns the matching definition at rank 1."""
    envelope = indexed_relevance["search"].search("ArticleService.getArticle", limit=6)
    results = envelope["results"]
    assert results
    assert results[0]["role"] == "definition"
    assert "getArticle" in results[0]["fqn"]
    assert _match_boost(results[0])["tier"] == "exact_fqn"


def test_non_exact_symbol_query_receives_no_exact_boost(
    indexed_relevance: dict[str, Any],
) -> None:
    """A merely similar query gets no exact-symbol boost."""
    envelope = indexed_relevance["search"].search("ArticleServ", limit=6)
    for result in envelope["results"]:
        evidence = _match_boost(result)
        assert evidence is None or evidence["tier"] not in ("exact_symbol", "exact_fqn")


def test_ambiguous_symbol_query_does_not_apply_exact_symbol(
    indexed_overload_symbols: dict[str, Any],
) -> None:
    """An overloaded name receives no exact-symbol boost."""
    envelope = indexed_overload_symbols["search"].search("save", limit=10)
    for result in envelope["results"]:
        evidence = _match_boost(result)
        assert evidence is None or evidence["tier"] != "exact_symbol"


# --- Proportional path-term queries -------------------------


def test_path_matching_file_outranks_equal_content_match(
    indexed_match_boost: dict[str, Any],
) -> None:
    """The path-matching twin outranks the equal-content non-match."""
    envelope = indexed_match_boost["search"].search("authentication filter", limit=6)
    paths = _paths(envelope)
    auth_index = next(i for i, p in enumerate(paths) if p.endswith("auth/filter.py"))
    other_index = next(i for i, p in enumerate(paths) if p.endswith("other/filter.py"))
    assert auth_index < other_index


def test_no_path_overlap_receives_no_boost(indexed_match_boost: dict[str, Any]) -> None:
    """A query with no path overlap receives no path boost."""
    envelope = indexed_match_boost["search"].search("wqrble token waffle", limit=5)
    assert envelope["results"] == []


# --- Determinism --------------------------------------------


def test_repeated_query_ordering_is_identical(indexed_match_boost: dict[str, Any]) -> None:
    """Identical query and index state produce identical ordering."""
    search = indexed_match_boost["search"]
    first = search.search("authentication filter", limit=6)
    second = search.search("authentication filter", limit=6)
    assert [r["chunk_id"] for r in first["results"]] == [r["chunk_id"] for r in second["results"]]


# --- Test-repo corpus --------------------------------------------


@pytest.mark.test_repo
def test_spring_boot_main_application_ranks_main_class_first() -> None:
    """`spring boot main application` returns the main class at rank 1.

    Requires the ``test-repo`` submodule; not run on CI.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from tests.conftest import _indexed_components

    repo = Path(__file__).resolve().parents[2] / "test-repo"
    if not repo.exists():
        pytest.skip("test-repo submodule not checked out")
    with tempfile.TemporaryDirectory(prefix="test_repo_eval_") as tmp:
        work = Path(tmp) / "test-repo"
        # ``.context`` holds generated index data (and, after a test_repo run, a
        # live daemon socket) that copytree cannot read; index the copy fresh.
        shutil.copytree(repo, work, ignore=shutil.ignore_patterns(".context"))
        components = _indexed_components(work, work / ".context")
        envelope = components["search"].search("spring boot main application", limit=5)
    assert envelope["results"]
    assert "RealWorldApplication" in envelope["results"][0]["file_path"]
