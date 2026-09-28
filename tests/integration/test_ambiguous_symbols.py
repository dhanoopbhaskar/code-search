from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
from src.engine.parser import ASTParser
from src.engine.redactor import Redactor
from src.engine.symbols import SymbolExtractor, SymbolStore
from src.mcp.server import _call_neighbors_payload, _definition_payload

AMBIGUOUS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "ambiguous_symbols"

AMBIGUOUS_NAMES = ("getBySlug", "save", "register", "generateToken", "favoriteArticle")


@pytest.fixture
def ambiguous_components(tmp_path: Path) -> dict[str, Any]:
    from src.engine.audit import AuditDatabase

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)
    metadata_store = IndexMetadataStore(db)
    metadata_store.set_index_status("ready")
    audit_db = AuditDatabase(tmp_path / "audit.db")
    audit_db.initialize()

    for py_file in sorted(AMBIGUOUS_FIXTURE.rglob("*.py")):
        source = py_file.read_bytes()
        extractor = SymbolExtractor(ASTParser())
        syms = extractor.extract_symbols(py_file, source)
        id_map = symbol_store.insert_symbols_batch(syms)

        edges = extractor.extract_edges(py_file, source)
        resolved = []
        for edge in edges:
            src_id = id_map.get(edge["source_fqn"])
            tgt_id = id_map.get(edge["target_fqn"])
            if src_id is not None and tgt_id is not None:
                resolved.append(
                    {
                        "source_symbol_id": src_id,
                        "target_symbol_id": tgt_id,
                        "edge_type": edge["edge_type"],
                        "source_range": edge.get("source_range"),
                        "target_range": edge.get("target_range"),
                    }
                )
        if resolved:
            edge_store.insert_edges_batch(resolved)

    return {
        "db": db,
        "symbol_store": symbol_store,
        "edge_store": edge_store,
        "metadata": metadata_store,
        "audit_db": audit_db,
        "redactor": Redactor(),
        "settings": settings,
        "context_dir": tmp_path,
    }


@pytest.mark.integration
def test_call_neighbors_ambiguous_names_return_candidates(
    ambiguous_components: dict[str, Any],
) -> None:
    """Ambiguous names yield a candidate list, not a crash or empty result."""
    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]

    for name in AMBIGUOUS_NAMES:
        payload = _call_neighbors_payload(store, edge_store, name)
        data = json_loads(payload)
        assert data["ambiguous"] is True, f"{name} should be flagged ambiguous"
        assert data["symbol"] is None
        assert data["callers"] == []
        assert data["callees"] == []
        assert len(data["candidates"]) >= 2, f"{name} should have >= 2 candidates"
        for cand in data["candidates"]:
            assert cand["name"] == name
            for key in ("fqn", "conventional_fqn", "kind", "file_path", "line_start", "line_end"):
                assert key in cand, f"missing candidate key: {key}"


@pytest.mark.integration
def test_definition_ambiguous_names_report_matches(
    ambiguous_components: dict[str, Any],
) -> None:
    """Ambiguous definition names report matches, never `found: false`."""
    store = ambiguous_components["symbol_store"]
    redactor = Redactor()

    for name in ("generateToken", "getCurrentUser", "favoriteArticle"):
        data = json_loads(_definition_payload(store, redactor, name))
        assert data["found"] is True, f"{name} should report found"
        assert data["ambiguous"] is True, f"{name} should be flagged ambiguous"
        assert data["symbol"] is None
        assert data["parent"] is None
        assert len(data["candidates"]) >= 2, f"{name} should have >= 2 candidates"
        for cand in data["candidates"]:
            assert cand["name"] == name
            for key in (
                "fqn",
                "conventional_fqn",
                "kind",
                "file_path",
                "line_start",
                "line_end",
                "parent_name",
            ):
                assert key in cand, f"missing candidate key: {key}"


@pytest.mark.integration
def test_definition_missing_name_stays_not_found(
    ambiguous_components: dict[str, Any],
) -> None:
    """A genuinely missing name still returns `found: false`."""
    store = ambiguous_components["symbol_store"]
    redactor = Redactor()

    data = json_loads(_definition_payload(store, redactor, "definitelyNotReal123"))
    assert data["found"] is False
    assert data["symbol"] is None
    assert data["parent"] is None


@pytest.mark.integration
def test_definition_and_call_neighbors_candidates_identical(
    ambiguous_components: dict[str, Any],
) -> None:
    """Both tools return byte-identical candidate lists for the same name."""
    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]
    redactor = Redactor()

    for name in AMBIGUOUS_NAMES:
        defn = json_loads(_definition_payload(store, redactor, name))
        graph = json_loads(_call_neighbors_payload(store, edge_store, name))
        assert defn.get("ambiguous") is True
        assert graph.get("ambiguous") is True
        assert defn["candidates"] == graph["candidates"], f"{name} candidates differ"
        assert [c["fqn"] for c in defn["candidates"]] == [c["fqn"] for c in graph["candidates"]]


@pytest.mark.integration
def test_cli_json_candidates_match_mcp_payloads(
    ambiguous_components: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI ``--json`` candidate arrays are byte-identical to the MCP payloads."""
    from argparse import Namespace

    from src.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_initialize_components", lambda _ctx: ambiguous_components)

    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]
    redactor = ambiguous_components["redactor"]

    for name in AMBIGUOUS_NAMES:
        defn_payload = json_loads(_definition_payload(store, redactor, name))
        graph_payload = json_loads(_call_neighbors_payload(store, edge_store, name))

        args = Namespace(
            fqn=name,
            verbose=False,
            context_dir=str(ambiguous_components["context_dir"]),
        )

        args.json = True
        cli_main.cmd_symbol(args)
        sym_out = json.loads(capsys.readouterr().out)
        assert sym_out["candidates"] == defn_payload["candidates"], f"{name} symbol mismatch"

        args.direction = "both"
        args.depth = 1
        args.transitive = False
        cli_main.cmd_graph(args)
        graph_out = json.loads(capsys.readouterr().out)
        assert graph_out["candidates"] == graph_payload["candidates"], f"{name} graph mismatch"


@pytest.mark.integration
def test_chosen_symbol_with_no_edges_not_an_error(
    ambiguous_components: dict[str, Any],
) -> None:
    """A resolved symbol with no recorded callers/callees is not an error."""
    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]

    data = json_loads(_call_neighbors_payload(store, edge_store, "unused_helper"))
    assert data.get("ambiguous", False) is False
    assert data["symbol"] is not None
    assert data["callers"] == []
    assert data["callees"] == []


@pytest.mark.integration
def test_test_file_candidates_listed_alongside_production(
    ambiguous_components: dict[str, Any],
) -> None:
    """Test-vs-production duplicates are both listed as candidates."""
    store = ambiguous_components["symbol_store"]
    redactor = ambiguous_components["redactor"]

    data = json_loads(_definition_payload(store, redactor, "getBySlug"))
    assert data["ambiguous"] is True
    file_paths = [c["file_path"] for c in data["candidates"]]
    assert any(p.endswith("test_views.py") for p in file_paths), "test-file candidate missing"
    assert any(not p.endswith("test_views.py") for p in file_paths), "prod candidate missing"


@pytest.mark.integration
def test_definition_source_code_empty_when_file_missing(
    ambiguous_components: dict[str, Any],
) -> None:
    """A symbol whose source file vanished yields source_code: ``""``, not an error."""
    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]
    redactor = ambiguous_components["redactor"]
    db = ambiguous_components["db"]

    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("ghost.py::GhostHelper", "GhostHelper", "function", "ghost.py", 1, 3, 0, 10, "python"),
        )

    defn = json_loads(_definition_payload(store, redactor, "GhostHelper"))
    assert defn["found"] is True
    assert defn["symbol"]["source_code"] == ""

    graph = json_loads(_call_neighbors_payload(store, edge_store, "GhostHelper"))
    assert graph["symbol"] is not None
    assert graph["callers"] == []
    assert graph["callees"] == []


@pytest.mark.integration
def test_call_neighbors_unique_name_unchanged(ambiguous_components: dict[str, Any]) -> None:
    """Unique symbols keep resolving exactly as before."""
    store = ambiguous_components["symbol_store"]
    edge_store = ambiguous_components["edge_store"]

    data = json_loads(_call_neighbors_payload(store, edge_store, "isTokenValid"))
    assert data.get("ambiguous", False) is False
    assert data["symbol"] is not None
    assert data["symbol"]["kind"] == "method"
    assert data["symbol"]["file_path"].endswith("service.py")


def json_loads(payload: str) -> dict[str, Any]:
    return json.loads(payload)
