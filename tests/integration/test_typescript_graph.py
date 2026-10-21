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


def _caller_fqns(indexed: dict[str, Any], target_reference: str) -> set[str]:
    """Return the caller FQNs for a resolved symbol reference."""
    target, _candidates = indexed["symbol_store"].resolve_symbol(target_reference)
    assert target is not None, f"{target_reference} must be an extracted symbol"
    call_graph = indexed["edge_store"].get_call_graph(target["id"], direction="callers")
    return {row["fqn"] for row in call_graph["callers"]}


def test_typescript_field_and_local_receiver_calls_resolve(
    indexed_tsreact: dict[str, Any],
) -> None:
    """Declared field/local types resolve receiver calls cross-file."""
    callers = _caller_fqns(indexed_tsreact, "Loader.fetch")
    assert any(fqn.endswith("ArticleService.load") for fqn in callers)
    assert any("loadViaParam" in fqn for fqn in callers)

    service_callers = _caller_fqns(indexed_tsreact, "ArticleService.load")
    assert any("loadThroughService" in fqn for fqn in service_callers)


def test_typescript_this_and_namespace_calls_resolve(
    indexed_tsreact: dict[str, Any],
) -> None:
    """``this.method`` and ``import * as ns`` member calls resolve."""
    helper_callers = _caller_fqns(indexed_tsreact, "ArticleService.helper")
    assert any(fqn.endswith("ArticleService.load") for fqn in helper_callers)

    loaders = _caller_fqns(indexed_tsreact, "loadArticles")
    assert any("NamespaceConsumer" in fqn for fqn in loaders)


def test_typescript_external_member_call_stays_unresolved(
    indexed_tsreact: dict[str, Any],
) -> None:
    """A library member call (``store.dispatch``) is captured as unresolved."""
    with indexed_tsreact["db"].connect() as conn:
        rows = conn.execute(
            "SELECT e.resolved, e.target_raw FROM graph_edges e "
            "JOIN symbols s ON s.id = e.source_symbol_id "
            "WHERE s.fqn LIKE '%dispatchArticles%' AND e.edge_type = 'CALLS';"
        ).fetchall()
    unresolved = [row["target_raw"] for row in rows if row["resolved"] == 0]
    assert any("store.dispatch" in (raw or "") for raw in unresolved)


def test_search_reports_token_savings(indexed_tsreact: dict[str, Any]) -> None:
    """The ranked envelope reports returned vs whole-file token estimates."""
    envelope = indexed_tsreact["search"].search("loadArticles", limit=5)
    savings = envelope["token_savings"]
    assert savings["files"] >= 1
    assert savings["returned_tokens"] >= 0
    assert savings["full_file_tokens"] >= savings["returned_tokens"]
    assert 0.0 <= savings["saved_percent"] <= 100.0
