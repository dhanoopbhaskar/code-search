"""TypeScript graph extraction over the TS/React fixture.

Pins the ES-module import resolution (relative paths, barrel ``index`` files,
and ``tsconfig`` path aliases) and the call edges produced by arrow-component
and thunk declarations.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def indexed_tsreact(tmp_path: Path) -> dict[str, Any]:
    """Index a copy of the TS/React fixture."""
    repo = tmp_path / "tsreact_repo"
    shutil.copytree(FIXTURES_DIR / "tsreact", repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def test_typescript_imports_resolve_relative_barrel_and_alias(
    indexed_tsreact: dict[str, Any],
) -> None:
    """Relative, barrel, and tsconfig-alias imports all resolve to files."""
    with indexed_tsreact["db"].connect() as conn:
        rows = conn.execute(
            "SELECT source_path, target_path, resolved, target_raw "
            "FROM module_edges ORDER BY source_path, target_raw;"
        ).fetchall()
    resolved = {
        (row["source_path"], row["target_raw"]): row["target_path"]
        for row in rows
        if row["resolved"] == 1
    }

    assert resolved[("src/ArticlesViewer.tsx", "./store/articlesSlice")] == (
        "src/store/articlesSlice.ts"
    )
    assert resolved[("src/components/index.ts", "./Button")] == "src/components/Button.tsx"
    assert resolved[("src/features/ArticleList.tsx", "@/components")] == ("src/components/index.ts")


def test_typescript_call_edges_are_resolved_and_reverse_traversable(
    indexed_tsreact: dict[str, Any],
) -> None:
    """Calls inside arrow components/thunks resolve, and callers can be found."""
    target, _candidates = indexed_tsreact["symbol_store"].resolve_symbol("loadArticles")
    assert target is not None, "loadArticles must be an extracted symbol"

    call_graph = indexed_tsreact["edge_store"].get_call_graph(target["id"], direction="callers")
    caller_names = {Path(row["fqn"].split("::")[-1]).name for row in call_graph["callers"]}
    assert {"ArticlesViewer", "ArticleList", "fetchArticles"} <= caller_names


def test_code_intent_suppresses_lockfile_results(indexed_tsreact: dict[str, Any]) -> None:
    """A code-shaped query does not surface the lockfile infra record."""
    envelope = indexed_tsreact["search"].search("ArticlesViewer react", limit=10)
    file_roles = {result.get("file_role") for result in envelope["results"]}
    assert "infra" not in file_roles
    assert not any(
        result["file_path"].endswith("package-lock.json") for result in envelope["results"]
    )


def test_score_sources_exposes_ranking_multipliers(indexed_tsreact: dict[str, Any]) -> None:
    """``score_sources`` records the class/content multipliers and boosts."""
    envelope = indexed_tsreact["search"].search("ArticlesViewer", limit=5)
    sources = envelope["results"][0]["score_sources"]
    assert {"rank_class", "content", "test_noise", "infra"} <= set(sources["multipliers"])
    assert {"exact_match", "min_vector_lift"} <= set(sources["additive"])
