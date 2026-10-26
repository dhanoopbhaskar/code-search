"""Unit tests for the bounded architecture aspect surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.graph import EdgeStore, GraphDatabase
from code_search.engine.graph_query import GraphQueryService
from code_search.engine.symbols import SymbolStore


@pytest.fixture
def service(tmp_path: Path) -> GraphQueryService:
    """Return a query service over a small graph with an import cycle."""
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES "
            "('/repo/src/api.py::main', 'main', 'function', '/repo/src/api.py', 0, 4, 0, 1, "
            "'python'), "
            "('/repo/src/api.py::Controller', 'Controller', 'class', '/repo/src/api.py', 6, 20, "
            "0, 1, 'python'), "
            "('/repo/src/api.py::Controller.handle', 'handle', 'method', '/repo/src/api.py', "
            "8, 12, 4, 8, 'python'), "
            "('/repo/tests/test_api.py::test_handle', 'test_handle', 'function', "
            "'/repo/tests/test_api.py', 0, 4, 0, 1, 'python'), "
            "('/repo/src/store.py::Store', 'Store', 'class', '/repo/src/store.py', 0, 10, 0, 1, "
            "'java');"
        )
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
            "resolution_tier, resolved) VALUES (2, 3, 'CALLS', 'exact', 1);"
        )
        conn.executemany(
            "INSERT INTO module_edges (source_path, target_path, relation, resolved) "
            "VALUES (?, ?, 'IMPORTS', 1);",
            [("src/api.py", "src/store.py"), ("src/store.py", "src/api.py")],
        )
        conn.execute(
            "INSERT INTO index_metadata (key, value) VALUES ('index_generation', 'gen-1');"
        )
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_root', '/repo');")
    return GraphQueryService(db, SymbolStore(db, settings), EdgeStore(db), None, settings)


def test_architecture_overview_is_bounded(service: GraphQueryService) -> None:
    """The default overview omits the expensive sections."""
    payload = service.architecture()

    assert payload["outcome"] == "resolved"
    assert payload["aspects"] == ["overview"]
    assert payload["languages"] == {"java": 1, "python": 4}
    assert payload["packages"] == [
        {"path": "src", "symbols": 4},
        {"path": "tests", "symbols": 1},
    ]
    assert payload["entry_points"]["by_reason"] == {"main": 1, "test": 1}
    assert "hotspots" not in payload
    assert "cycles" not in payload
    assert payload["index_generation"] == "gen-1"


def test_architecture_all_includes_cycles_and_hotspots(service: GraphQueryService) -> None:
    """``all`` expands to every aspect, including Tarjan import components."""
    payload = service.architecture(aspects={"all"})

    assert payload["aspects"] == [
        "clusters",
        "cycles",
        "dependencies",
        "entry_points",
        "hotspots",
        "overview",
        "structure",
    ]
    assert payload["cycles"] == [["src/api.py", "src/store.py"]]
    assert payload["cycle_semantics"].startswith("strongly connected components")
    assert payload["hotspots"]
    assert payload["edge_stats"]["CALLS"]["resolved"] == 1


def test_architecture_unsupported_aspect_is_an_outcome(service: GraphQueryService) -> None:
    """An unknown aspect is refused with the supported set."""
    payload = service.architecture(aspects={"hotspots", "nope"})

    assert payload["outcome"] == "invalid_argument"
    assert "nope" in payload["error"]
    assert "hotspots" in payload["supported_aspects"]


def test_architecture_hotspots_and_clusters_only_when_requested(
    service: GraphQueryService,
) -> None:
    """Requesting sections does not compute the others."""
    payload = service.architecture(aspects={"hotspots", "clusters"})

    assert "hotspots" in payload
    assert "clusters" in payload
    assert "packages" not in payload
    assert "cycles" not in payload
