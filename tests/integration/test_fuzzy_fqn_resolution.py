"""Integration tests for fuzzy FQN resolution / goto definition.

Covers the unique partial-resolution path, the deprecated ranking
scenario, cross-consumer consistency, and the no-schema-change
guard. The ranked-search recognition path lives in
``test_partial_symbol_search.py``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.engine.redactor import Redactor
from src.mcp.server import _call_neighbors_payload, _definition_payload


def _build(tmp_path: Path, fixture: str, name: str) -> dict[str, Any]:
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / name
    shutil.copytree(FIXTURES_DIR / fixture, repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    comps["redactor"] = Redactor()
    return comps


@pytest.fixture
def transparency_comps(tmp_path: Path) -> dict[str, Any]:
    return _build(tmp_path, "transparency", "transparency_repo")


@pytest.fixture
def deprecated_comps(tmp_path: Path) -> dict[str, Any]:
    return _build(tmp_path, "deprecated_symbols", "deprecated_repo")


# --- Unique partial resolution -----------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_unique_partial_references_resolve_in_one_step(
    transparency_comps: dict[str, Any],
) -> None:
    """Bare leaf, parent-qualified, and suffix all resolve."""
    store = transparency_comps["symbol_store"]
    exact_fqn = None
    with transparency_comps["db"].connect() as conn:
        row = conn.execute(
            "SELECT fqn FROM symbols WHERE name = 'delete' AND kind = 'method' LIMIT 1;"
        ).fetchone()
        exact_fqn = row["fqn"]
    exact = store.resolve_name(exact_fqn)
    assert exact["kind"] == "exact"

    for query in ("delete", "ArticleService.delete", "article.ArticleService.delete"):
        envelope = store.resolve_name(query)
        assert envelope["kind"] == "exact", (query, envelope)
        assert envelope["outcome"] == "resolved"
        assert envelope["symbol"]["fqn"] == exact_fqn
        assert envelope["symbol"]["file_path"] == exact["symbol"]["file_path"]
        assert envelope["symbol"]["line_start"] == exact["symbol"]["line_start"]
        assert envelope["candidates"] == []


@pytest.mark.integration
@pytest.mark.slow
def test_unique_partial_resolution_air_gap(transparency_comps: dict[str, Any]) -> None:
    """Resolution performs no outbound connection."""
    import socket

    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("resolution must not open a network connection")

    original = socket.socket.connect
    socket.socket.connect = _blocked  # type: ignore[method-assign]
    try:
        transparency_comps["symbol_store"].resolve_name("ArticleService.delete")
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]


# --- Edge cases: not-found and suggestions ------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_not_found_and_suggestion_never_resolve(transparency_comps: dict[str, Any]) -> None:
    """Misspellings, wrong parents, and empty input never resolve."""
    store = transparency_comps["symbol_store"]

    misspelled = store.resolve_name("delet")
    assert misspelled["symbol"] is None
    assert misspelled["outcome"] == "not_found"
    assert misspelled["candidates"]

    wrong_parent = store.resolve_name("WrongClass.save")
    assert wrong_parent["symbol"] is None
    assert wrong_parent["outcome"] == "not_found"

    empty = store.resolve_name("")
    assert empty["symbol"] is None
    assert empty["outcome"] == "not_found"
    assert empty["candidates"] == []

    whitespace = store.resolve_name("   ")
    assert whitespace["outcome"] == "not_found"


@pytest.mark.integration
@pytest.mark.slow
def test_signature_inconsistent_falls_back_to_ranked_list(
    transparency_comps: dict[str, Any],
) -> None:
    """An inconsistent signature never returns a contradicting resolution."""
    envelope = transparency_comps["symbol_store"].resolve_name("ArticleService.save(boolean)")
    assert envelope["symbol"] is None
    assert envelope["outcome"] == "ambiguous"
    assert all(c["signature"]["normalized"] != "boolean" for c in envelope["candidates"])


# --- Deprecated ranking -------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_deprecated_ranks_after_non_deprecated(deprecated_comps: dict[str, Any]) -> None:
    """The non-deprecated overload is ranked first, never auto-selected."""
    envelope = deprecated_comps["symbol_store"].resolve_name("LegacyService.process")
    assert envelope["kind"] == "ambiguous"
    assert envelope["outcome"] == "ambiguous"
    assert envelope["symbol"] is None
    candidates = envelope["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["deprecated"] is False
    assert candidates[1]["deprecated"] is True
    assert "non_deprecated" in candidates[0]["evidence"]
    assert "deprecated" in candidates[1]["evidence"]


@pytest.mark.integration
@pytest.mark.slow
def test_all_deprecated_candidates_still_returned(deprecated_comps: dict[str, Any]) -> None:
    """Edge case: every deprecated candidate is returned, none auto-selected."""
    envelope = deprecated_comps["symbol_store"].resolve_name("FullyDeprecatedService.run")
    assert envelope["kind"] == "ambiguous"
    assert envelope["symbol"] is None
    assert len(envelope["candidates"]) == 2
    assert all(c["deprecated"] is True for c in envelope["candidates"])


# --- Cross-consumer consistency ----------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_cross_consumer_consistency(
    transparency_comps: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every consumer agrees on outcome and candidate order."""
    comps = transparency_comps
    store = comps["symbol_store"]

    envelope = store.resolve_name("ArticleService.save")
    assert envelope["outcome"] == "ambiguous"

    mcp_def = json.loads(
        _definition_payload(store, comps["redactor"], "ArticleService.save", comps.get("freshness"))
    )
    assert mcp_def["outcome"] == envelope["outcome"]
    assert [c["fqn"] for c in mcp_def["candidates"]] == [c["fqn"] for c in envelope["candidates"]]

    mcp_neigh = json.loads(
        _call_neighbors_payload(
            store, comps["edge_store"], "ArticleService.save", "both", 1, comps.get("freshness")
        )
    )
    assert mcp_neigh["outcome"] == envelope["outcome"]
    assert [c["fqn"] for c in mcp_neigh["candidates"]] == [c["fqn"] for c in envelope["candidates"]]

    from src.engine.daemon import QueryDaemon

    daemon_symbol = QueryDaemon._do_symbol(comps, {"fqn": "ArticleService.save"})
    assert daemon_symbol["payload"]["outcome"] == envelope["outcome"]
    assert [c["fqn"] for c in daemon_symbol["payload"]["candidates"]] == [
        c["fqn"] for c in envelope["candidates"]
    ]

    daemon_graph = QueryDaemon._do_graph(comps, {"fqn": "ArticleService.save", "depth": 1})
    assert daemon_graph["payload"]["outcome"] == envelope["outcome"]

    # Ranked-search symbol context reads the same shared envelope.
    match_context = comps["search"]._build_query_match_context("ArticleService.save")
    assert match_context.symbol_resolved is True

    # A unique partial reference agrees across consumers too.
    unique = store.resolve_name("ArticleService.delete")
    assert unique["outcome"] == "resolved"
    mcp_unique = json.loads(
        _definition_payload(
            store, comps["redactor"], "ArticleService.delete", comps.get("freshness")
        )
    )
    assert mcp_unique["outcome"] == "resolved"
    assert mcp_unique["symbol"]["fqn"] == unique["symbol"]["fqn"]

    # Ordinary natural-language queries are unaffected.
    nl_context = comps["search"]._build_query_match_context("where is the article schema defined")
    assert nl_context.symbol_resolved is False


# --- No schema / AST / FQN change -----------------------------------


@pytest.mark.integration
def test_no_schema_or_migration_change(transparency_comps: dict[str, Any]) -> None:
    """The schema version and symbol/graph columns are unchanged."""
    from src.engine.graph import SCHEMA_VERSION

    assert SCHEMA_VERSION == 13
    db = transparency_comps["db"]
    with db.connect() as conn:
        symbol_cols = {row["name"] for row in conn.execute("PRAGMA table_info(symbols);")}
        edge_cols = {row["name"] for row in conn.execute("PRAGMA table_info(graph_edges);")}
    assert symbol_cols == {
        "id",
        "fqn",
        "name",
        "kind",
        "file_path",
        "line_start",
        "line_end",
        "column_start",
        "column_end",
        "docstring",
        "declared_rules",
        "language",
        "conventional_fqn",
        "parent_symbol_id",
        "created_at",
        "updated_at",
    }
    assert edge_cols == {
        "id",
        "source_symbol_id",
        "target_symbol_id",
        "edge_type",
        "source_range",
        "target_range",
        "resolution_tier",
        "resolved",
        "target_raw",
        "created_at",
    }


@pytest.mark.integration
@pytest.mark.slow
def test_no_ast_or_fqn_generation_change(deprecated_comps: dict[str, Any]) -> None:
    """FQN generation and AST annotation extraction are pinned.

    FQN generation is unchanged — ``<file>::<Parent>.<name>(<params>)`` with the
    package-qualified ``conventional_fqn``. The one AST-extraction change is
    metadata-only: the existing ``marker_annotation`` node is read for
    ``@Deprecated`` into the existing ``declared_rules`` text, so the extracted
    symbol set, parse tree, and storage schema are untouched.
    """
    repo = deprecated_comps["repo"]
    db = deprecated_comps["db"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.name, s.fqn, s.conventional_fqn, s.declared_rules, "
            "p.name AS parent_name "
            "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
            "WHERE s.name = 'process' ORDER BY s.fqn;"
        ).fetchall()
    assert len(rows) == 2
    deprecated = next(r for r in rows if r["declared_rules"] == "@Deprecated")
    sibling = next(r for r in rows if r["declared_rules"] is None)

    # FQN generation is byte-identical to the pre-change form.
    assert deprecated["fqn"] == (
        f"{repo}/src/main/java/com/example/legacy/LegacyService.java::LegacyService.process(String)"
    )
    assert deprecated["conventional_fqn"] == "com.example.legacy.LegacyService.process(String)"
    assert deprecated["parent_name"] == "LegacyService"
    assert sibling["fqn"] == (
        f"{repo}/src/main/java/com/example/legacy/LegacyService.java::LegacyService.process(int)"
    )
    assert sibling["conventional_fqn"] == "com.example.legacy.LegacyService.process(int)"
    assert sibling["parent_name"] == "LegacyService"

    # The metadata-only marker-annotation extraction is the sole AST deviation.
    assert deprecated["declared_rules"] == "@Deprecated"
    assert sibling["declared_rules"] is None
