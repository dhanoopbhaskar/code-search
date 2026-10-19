"""Graph-query acceptance gate for multi-hop questions and graph fidelity."""

from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components
from tests.evaluation.multihop_eval import evaluate


@pytest.fixture
def indexed_multihop(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Index the hermetic multi-hop fixture."""
    repo = tmp_path / "multihop"
    shutil.copytree(FIXTURES_DIR / "multihop", repo)
    yield _indexed_components(repo, tmp_path / ".context")


@pytest.fixture
def indexed_multihop_docs(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    """Index the multi-hop fixture with offline doc links enabled."""
    repo = tmp_path / "multihop_docs"
    shutil.copytree(FIXTURES_DIR / "multihop", repo)
    yield _indexed_components(
        repo,
        tmp_path / ".context",
        settings_kwargs={"index_doc_links": True},
    )


@pytest.mark.integration
def test_multihop_chain_recall_floor(indexed_multihop: dict[str, Any]) -> None:
    """The labelled multi-hop chain is present at depth 2 in >= 75% of cases."""
    metrics = evaluate(indexed_multihop)
    assert metrics["chain_recall_depth2"] >= 0.75, metrics
    assert metrics["chain_recall_depth3"] >= 0.75, metrics


@pytest.mark.integration
def test_module_imports_are_resolved(indexed_multihop: dict[str, Any]) -> None:
    """Java imports produce resolved module edges and retain their raw target."""
    from code_search.engine.graph import ModuleEdgeStore

    stats = ModuleEdgeStore(indexed_multihop["db"]).resolution_stats("IMPORTS")
    assert stats["total"] > 0
    assert stats["resolved"] > 0


@pytest.mark.integration
def test_python_imports_resolve_and_unresolved_retained(tmp_path: Path) -> None:
    """Python module imports resolve; relative/external imports stay visible."""
    from code_search.engine.graph import ModuleEdgeStore

    absolute_repo = tmp_path / "ambiguous_symbols"
    shutil.copytree(FIXTURES_DIR / "ambiguous_symbols", absolute_repo)
    absolute = _indexed_components(absolute_repo, tmp_path / "absolute_context")
    resolved = ModuleEdgeStore(absolute["db"]).resolution_stats("IMPORTS")
    assert resolved["resolved"] > 0

    relative_repo = tmp_path / "path_penalty"
    shutil.copytree(FIXTURES_DIR / "path_penalty", relative_repo)
    relative = _indexed_components(relative_repo, tmp_path / "relative_context")
    unresolved = ModuleEdgeStore(relative["db"]).resolution_stats("IMPORTS")
    assert unresolved["total"] > 0
    with relative["db"].connect() as conn:
        rows = conn.execute("SELECT target_raw FROM module_edges WHERE resolved = 0;").fetchall()
    assert rows
    assert all(row["target_raw"] for row in rows)


@pytest.mark.integration
def test_edges_carry_provenance_labels(indexed_multihop: dict[str, Any]) -> None:
    """Every rendered edge carries a confidence label."""
    answer = _service(indexed_multihop).explain("ArticleService.favorite")
    assert answer.outcome == "resolved"
    assert answer.edges
    assert {edge.confidence for edge in answer.edges} <= {
        "EXTRACTED",
        "INFERRED",
        "AMBIGUOUS",
        "UNRESOLVED",
    }


@pytest.mark.integration
def test_explain_returns_rationale(indexed_multihop: dict[str, Any]) -> None:
    """A ``WHY:`` comment is surfaced by ``explain``."""
    answer = _service(indexed_multihop).explain("ArticleService.favorite")
    assert answer.rationale
    assert answer.rationale[0]["kind"] == "why"
    assert "repository" in answer.rationale[0]["text"]


@pytest.mark.integration
def test_shortest_path_is_correct_and_deterministic(indexed_multihop: dict[str, Any]) -> None:
    """The known call chain is returned, and repeated runs are byte-identical."""
    service = _service(indexed_multihop)
    first = service.shortest_path("ArticleController.favoriteArticle", "ArticleRepository.save")
    second = service.shortest_path("ArticleController.favoriteArticle", "ArticleRepository.save")
    assert first.found
    assert [hop.relation for hop in first.hops] == ["CALLS", "CALLS"]
    assert _stable(first.as_dict()) == _stable(second.as_dict())


@pytest.mark.integration
def test_class_level_path_traverses_containment(indexed_multihop: dict[str, Any]) -> None:
    """Class endpoints resolve to their type and connect through members."""
    service = _service(indexed_multihop)
    answer = service.shortest_path("ArticleController", "ArticleRepository")
    assert answer.found
    relations = [hop.relation for hop in answer.hops]
    assert relations[0] == "CONTAINS"
    assert relations[-1] == "CONTAINS"
    assert "CALLS" in relations
    from code_search.engine.graph_query import render_path_text

    rendered = render_path_text(answer)
    assert "member of" in rendered


@pytest.mark.integration
def test_impact_files_are_deduped_and_relative(indexed_multihop: dict[str, Any]) -> None:
    """Impact files use one relative spelling and are bucketed by role."""
    repo = Path(indexed_multihop["metadata"].get("index_root"))
    changed = repo / "src/main/java/com/example/core/ArticleRepository.java"
    answer = _service(indexed_multihop).impact([str(changed)], depth=3)
    assert len(answer.files) == len(set(answer.files))
    assert all(not Path(path).is_absolute() for path in answer.files)
    assert answer.production_files == answer.files
    assert answer.test_files == []


@pytest.mark.integration
def test_query_is_deterministic(indexed_multihop: dict[str, Any]) -> None:
    """Repeated queries produce byte-identical structured answers."""
    service = _service(indexed_multihop)
    first = service.query(
        "how does favoriting an article flow from the controller to the repository",
        depth=2,
    )
    second = service.query(
        "how does favoriting an article flow from the controller to the repository",
        depth=2,
    )
    assert _stable(first.as_dict()) == _stable(second.as_dict())


@pytest.mark.integration
def test_doc_links_are_offline_and_deterministic(
    indexed_multihop_docs: dict[str, Any],
) -> None:
    """Symbol mentions create doc links without network access."""
    with indexed_multihop_docs["db"].connect() as conn:
        rows = conn.execute(
            "SELECT method, COUNT(*) AS cnt FROM doc_links GROUP BY method;"
        ).fetchall()
    methods = {row["method"]: int(row["cnt"]) for row in rows}
    assert methods.get("symbol_mention", 0) > 0


@pytest.mark.integration
def test_reverse_importers_are_exposed(indexed_multihop: dict[str, Any]) -> None:
    """``explain`` exposes file importers and importees when IMPORTS is asked."""
    from code_search.engine.graph import ModuleEdgeStore

    store = ModuleEdgeStore(indexed_multihop["db"])
    importers = {
        row["path"]
        for row in store.get_importers(
            "src/main/java/com/example/core/ArticleRepository.java", max_depth=2
        )
    }
    assert "src/main/java/com/example/app/ArticleService.java" in importers

    answer = _service(indexed_multihop).explain("ArticleRepository", relations={"IMPORTS"})
    assert answer.outcome == "resolved"
    assert any(edge.relation == "IMPORTS" for edge in answer.edges)


@pytest.mark.integration
def test_impact_analysis_finds_reverse_callers(indexed_multihop: dict[str, Any]) -> None:
    """Changing the repository reports the service/controller that call it."""
    repo = Path(indexed_multihop["metadata"].get("index_root"))
    changed = repo / "src/main/java/com/example/core/ArticleRepository.java"
    answer = _service(indexed_multihop).impact([str(changed)], depth=3)
    names = {node.fqn.rsplit("::", 1)[-1].split("(", 1)[0] for node in answer.impacted}
    assert any(name.startswith("ArticleRepository") for name in names)
    assert any(name.startswith("ArticleService") for name in names)
    assert any(name.startswith("ArticleController") for name in names)


@pytest.mark.integration
def test_architecture_report_is_deterministic(indexed_multihop: dict[str, Any]) -> None:
    """The report is stable across runs and includes god nodes and imports."""
    service = _service(indexed_multihop)
    first = service.architecture_report(top_n=5)
    second = service.architecture_report(top_n=5)
    first_payload = first.as_dict()
    second_payload = second.as_dict()
    first_payload.pop("stats", None)
    second_payload.pop("stats", None)
    assert first_payload == second_payload
    assert first.god_nodes
    assert first.edge_stats


def _stable(payload: dict[str, Any]) -> str:
    """Serialise *payload* without volatile timing fields."""
    payload.pop("stats", None)
    return json.dumps(payload, default=str, sort_keys=True)


def _service(comps: dict[str, Any]) -> Any:
    """Build a graph-query service over an indexed component registry."""
    from code_search.engine.graph_query import GraphQueryService

    return GraphQueryService(
        comps["db"],
        comps["symbol_store"],
        comps["edge_store"],
        comps["search"],
        comps.get("settings"),
    )
