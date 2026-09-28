"""Unresolved/external callees surface as ``resolved: false`` edges.

Asserts that framework/external callee references (``repository.save``,
``saved.setPublished``) are persisted and returned as ``resolved: false``
edges carrying their raw reference text (``target_raw``);
resolved callees remain ``resolved: true``; and a typo callee and a
framework call are both ``resolved: false`` yet distinguishable by the raw
text each edge carries.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import _call_neighbors_payload


@pytest.fixture
def transparency_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over ``tests/fixtures/transparency/``."""
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


def _callees(comps: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    payload = _call_neighbors_payload(
        comps["symbol_store"], comps["edge_store"], symbol, "callees", 1, comps.get("freshness")
    )
    data = json.loads(payload)
    assert data.get("symbol") is not None, f"symbol {symbol} not resolved"
    return data.get("callees") or []


@pytest.mark.integration
@pytest.mark.slow
def test_framework_callee_surfaces_as_unresolved_with_raw_text(
    transparency_comps: dict[str, Any],
) -> None:
    """``repository.save`` — inherited from the external
    ``JpaRepository`` base, not indexed — appears as a ``resolved: false``
    edge carrying the raw reference text ``repository.save``.
    """
    comps = transparency_comps
    callees = _callees(comps, "ArticleService.save(Article)")
    unresolved = [c for c in callees if c.get("resolved") is False]
    assert unresolved, f"expected a resolved:false edge, got {callees}"
    raw_texts = {c.get("target_raw") for c in unresolved}
    assert "repository.save" in raw_texts, f"expected repository.save in {raw_texts}"


@pytest.mark.integration
@pytest.mark.slow
def test_local_var_receiver_resolves_when_target_indexed(
    transparency_comps: dict[str, Any],
) -> None:
    """A receiver-qualified call on a local variable whose
    declared type is in the corpus now resolves.

    ``Article saved = repository.save(article); saved.setPublished(true)``
    previously surfaced ``saved.setPublished`` as ``resolved: false`` because
    local-variable types were not collected; once the declared type (``Article``)
    is known and ``Article.setPublished`` is indexed, the edge resolves instead
    of being reported as an external callee.
    """
    comps = transparency_comps
    callees = _callees(comps, "ArticleService.save(Article,boolean)")
    resolved = [c for c in callees if c.get("resolved") is True]
    assert any("setPublished" in c.get("fqn", "") for c in resolved), (
        f"expected a resolved setPublished edge, got {callees}"
    )
    unresolved = [c for c in callees if c.get("resolved") is False]
    raw_texts = {c.get("target_raw") for c in unresolved}
    assert "saved.setPublished" not in raw_texts, (
        f"in-corpus local-var call must resolve, got raw {raw_texts}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_out_of_corpus_local_var_setter_stays_unresolved(tmp_path: Path) -> None:
    """A receiver-qualified call on a local variable whose
    declared type is NOT in the indexed corpus still surfaces as
    ``resolved: false`` with its raw reference text.
    """
    from tests.conftest import _indexed_components

    repo = tmp_path / "external_local_repo"
    (repo / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (repo / "src" / "main" / "java" / "com" / "example" / "Worker.java").write_text(
        "package com.example;\n"
        "\n"
        "public class Worker {\n"
        "    public void run() {\n"
        "        ExternalThing thing = new ExternalThing();\n"
        "        thing.apply();\n"
        "    }\n"
        "}\n"
    )
    comps = _indexed_components(repo, repo / ".context")
    callees = _callees(comps, "com.example.Worker.run")
    unresolved = [c for c in callees if c.get("resolved") is False]
    assert unresolved, f"expected a resolved:false edge, got {callees}"
    raw_texts = {c.get("target_raw") for c in unresolved}
    assert "thing.apply" in raw_texts, f"expected thing.apply in {raw_texts}"


@pytest.mark.integration
@pytest.mark.slow
def test_resolved_callee_remains_resolved(transparency_comps: dict[str, Any]) -> None:
    """``ArticleService.delete`` calls ``ArticleRepository.deleteById``,
    which is indexed, so the edge stays ``resolved: true`` (no false
    ``resolved: false`` claim for an in-corpus callee).
    """
    comps = transparency_comps
    callees = _callees(comps, "ArticleService.delete(long)")
    resolved = [c for c in callees if c.get("resolved") is True]
    assert resolved, f"expected a resolved:true edge, got {callees}"
    assert any("deleteById" in c.get("fqn", "") for c in resolved)
    assert all(c.get("target_raw") is None for c in resolved), "resolved edges carry no target_raw"


@pytest.mark.integration
@pytest.mark.slow
def test_typo_and_framework_callee_both_unresolved_distinguishable_by_raw(
    tmp_path: Path,
) -> None:
    """A typo callee (``reposiroty.save``) and a framework
    callee (``repository.save``) are both ``resolved: false`` but carry
    different ``target_raw`` text, so consumers can tell them apart.
    """
    from tests.conftest import _indexed_components

    repo = tmp_path / "typo_repo"
    (repo / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (repo / "src" / "main" / "java" / "com" / "example" / "Worker.java").write_text(
        "package com.example;\n"
        "\n"
        "public class Worker {\n"
        "    private final Repo repository;\n"
        "    public Worker(Repo repository) { this.repository = repository; }\n"
        "    public void run() {\n"
        '        repository.save("ok");\n'
        '        reposiroty.save("typo");\n'
        "    }\n"
        "}\n"
    )
    comps = _indexed_components(repo, repo / ".context")
    callees = _callees(comps, "com.example.Worker.run")
    unresolved = [c for c in callees if c.get("resolved") is False]
    raw_texts = {c.get("target_raw") for c in unresolved}
    assert "repository.save" in raw_texts, f"framework callee missing from {raw_texts}"
    assert "reposiroty.save" in raw_texts, f"typo callee missing from {raw_texts}"
    assert len(raw_texts) >= 2, "typo and framework callees must be distinguishable by raw text"
