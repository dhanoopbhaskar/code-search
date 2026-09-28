"""Multi-match partial names return a ranked, evidence-carrying list.

Asserts that ``ArticleService.save`` yields an ``ambiguous`` ranked
disambiguation list (most-specific / 2-arg first, no auto-selected symbol),
that each candidate carries its kind, location, signature, ``deprecated`` and
ranking ``evidence``, that a listed candidate's reported FQN round-trips to
that exact definition, and that a supplied signature is only ever a ranking
signal (never a filter that fabricates a contradicting resolution).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.engine.redactor import Redactor
from src.mcp.server import _definition_payload


@pytest.fixture
def transparency_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/transparency/``."""
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    comps["redactor"] = Redactor()
    return comps


@pytest.mark.integration
@pytest.mark.slow
def test_resolve_overloaded_save_returns_ranked_ambiguous_list(
    transparency_comps: dict[str, Any],
) -> None:
    """The most-specific overload is ranked first and none is selected."""
    envelope = transparency_comps["symbol_store"].resolve_name("ArticleService.save")
    assert envelope["kind"] == "ambiguous"
    assert envelope["outcome"] == "ambiguous"
    assert envelope["symbol"] is None
    assert envelope["ambiguous"] is True
    candidates = envelope["candidates"]
    assert len(candidates) == 2
    # Most parameters first (the 2-arg overload), never auto-selected.
    assert candidates[0]["signature"]["arity"] == 2
    assert candidates[1]["signature"]["arity"] == 1
    for candidate in candidates:
        assert candidate["kind"] == "method"
        assert candidate["file_path"]
        assert candidate["line_start"] is not None
        assert candidate["signature"]
        assert candidate["deprecated"] is False
        assert candidate["evidence"]
    assert "most_parameters" in candidates[0]["evidence"]
    assert "most_parameters" not in candidates[1]["evidence"]
    assert "parent_scope_match" in candidates[0]["evidence"]
    overloads = envelope["overloads"]
    assert len(overloads) == 2
    assert {o["arity"] for o in overloads} == {1, 2}


@pytest.mark.integration
@pytest.mark.slow
def test_resolve_overloaded_save_via_signature_resolves_one(
    transparency_comps: dict[str, Any],
) -> None:
    """A signature matching exactly one overload resolves it (with overload set)."""
    envelope = transparency_comps["symbol_store"].resolve_name("ArticleService.save(Article)")
    assert envelope["kind"] == "exact"
    assert envelope["outcome"] == "resolved"
    assert envelope["ambiguous"] is True
    assert envelope["symbol"]["signature"]["arity"] == 1
    assert len(envelope["overloads"]) == 2


@pytest.mark.integration
@pytest.mark.slow
def test_resolve_overloaded_save_signature_inconsistent_falls_back(
    transparency_comps: dict[str, Any],
) -> None:
    """An inconsistent signature never fabricates a resolved declaration."""
    envelope = transparency_comps["symbol_store"].resolve_name("ArticleService.save(boolean)")
    assert envelope["symbol"] is None
    assert envelope["kind"] == "ambiguous"
    assert envelope["outcome"] == "ambiguous"
    assert all(c["signature"]["normalized"] != "boolean" for c in envelope["candidates"])


@pytest.mark.integration
@pytest.mark.slow
def test_ranked_candidate_fqn_round_trips(transparency_comps: dict[str, Any]) -> None:
    """A listed candidate's reported FQN resolves to that definition."""
    store = transparency_comps["symbol_store"]
    envelope = store.resolve_name("ArticleService.save")
    top = envelope["candidates"][0]
    resolved = store.resolve_name(top["fqn"])
    assert resolved["kind"] == "exact"
    assert resolved["symbol"]["fqn"] == top["fqn"]


@pytest.mark.integration
@pytest.mark.slow
def test_resolve_overloaded_save_is_deterministic(transparency_comps: dict[str, Any]) -> None:
    """Repeating the lookup returns identical content and order."""
    store = transparency_comps["symbol_store"]
    first = store.resolve_name("ArticleService.save")["candidates"]
    second = store.resolve_name("ArticleService.save")["candidates"]
    assert [c["fqn"] for c in first] == [c["fqn"] for c in second]


@pytest.mark.integration
@pytest.mark.slow
def test_resolve_single_declaration_is_not_ambiguous(transparency_comps: dict[str, Any]) -> None:
    """A single-declaration name resolves with an empty overload set."""
    envelope = transparency_comps["symbol_store"].resolve_name("ArticleService.delete")
    assert envelope["kind"] == "exact"
    assert envelope["outcome"] == "resolved"
    assert envelope["ambiguous"] is False
    assert envelope["overloads"] == []


@pytest.mark.integration
@pytest.mark.slow
def test_mcp_definition_payload_carries_ranked_candidates(
    transparency_comps: dict[str, Any],
) -> None:
    """The MCP payload surfaces the same ranked candidates and ``outcome``."""
    comps = transparency_comps
    payload = _definition_payload(
        comps["symbol_store"], comps["redactor"], "ArticleService.save", comps.get("freshness")
    )
    data = json.loads(payload)
    assert data.get("found") is True
    assert data.get("ambiguous") is True
    assert data.get("outcome") == "ambiguous"
    assert data.get("symbol") is None
    assert len(data.get("overloads", [])) == 2
    assert data["candidates"][0]["signature"]["arity"] == 2
    assert data["candidates"][0]["evidence"]

    payload = _definition_payload(
        comps["symbol_store"], comps["redactor"], "ArticleService.delete", comps.get("freshness")
    )
    data = json.loads(payload)
    assert data.get("outcome") == "resolved"
    assert data.get("ambiguous") is False
    assert data.get("overloads") == []
