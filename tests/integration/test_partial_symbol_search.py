"""Partial symbol references are recognised by the ranked-search gate.

A symbol-shaped partial reference that names an indexed declaration is admitted
(not gated into an empty result) and surfaces the matching definition, while
ordinary natural-language queries keep their existing ranking.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest


def _build(tmp_path: Path, fixture: str, name: str) -> dict[str, Any]:
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / name
    shutil.copytree(FIXTURES_DIR / fixture, repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def transparency_search(tmp_path: Path) -> dict[str, Any]:
    return _build(tmp_path, "transparency", "transparency_search_repo")


@pytest.fixture
def relevance_search(tmp_path: Path) -> dict[str, Any]:
    return _build(tmp_path, "relevance", "relevance_search_repo")


@pytest.mark.integration
@pytest.mark.slow
def test_qualified_partial_symbol_reference_is_admitted(
    transparency_search: dict[str, Any],
) -> None:
    """A qualified partial reference is not gated into an empty result."""
    envelope = transparency_search["search"].search("ArticleService.save", limit=10)
    assert envelope["results"], "partial symbol query must not be gated into an empty result"
    assert envelope.get("no_match") is False
    definitions = [r for r in envelope["results"] if r.get("is_definition")]
    assert any("save" in (r.get("fqn") or "") for r in definitions), envelope["results"]


@pytest.mark.integration
@pytest.mark.slow
def test_bare_partial_symbol_reference_is_admitted(transparency_search: dict[str, Any]) -> None:
    """A bare member name that names an indexed symbol is admitted."""
    envelope = transparency_search["search"].search("delete", limit=10)
    assert envelope["results"], "bare partial symbol query must not be gated into an empty result"
    assert any(
        "delete" in (r.get("fqn") or "") and r.get("is_definition") for r in envelope["results"]
    )


@pytest.mark.integration
@pytest.mark.slow
def test_natural_language_query_ranking_unchanged(relevance_search: dict[str, Any]) -> None:
    """An ordinary natural-language query keeps its existing ranking."""
    search = relevance_search["search"]
    query = "where is the article schema defined"
    context = search._build_query_match_context(query)
    assert context.symbol_resolved is False
    envelope = search.search(query, limit=10)
    top_files = [r.get("file_path", "") for r in envelope["results"][:3]]
    assert any("V1__create_articles_table.sql" in path for path in top_files), top_files


@pytest.mark.integration
@pytest.mark.slow
def test_gibberish_query_still_rejected(transparency_search: dict[str, Any]) -> None:
    """The gate still rejects a genuine no-match query."""
    envelope = transparency_search["search"].search("wqrble token waffle", limit=10)
    assert envelope["results"] == []
