"""End-to-end interface implementation lookup.

Exercises the shared rule plus the MCP tool, CLI command, daemon action, and
the ``implements`` traversal direction over the curated multi-language fixture
corpus.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from src.engine.implementations import find_implementations
from src.mcp.server import _call_neighbors_payload

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# (language, declaring interface method name, expected direct implementer)
_DIRECT_CASES = [
    ("python", "speak", "Dog"),
    ("java", "speak", "Dog"),
    ("typescript", "speak", "Dog"),
    ("javascript", "speak", "Dog"),
    ("c_sharp", "Speak", "Dog"),
    ("cpp", "speak", "Dog"),
    ("kotlin", "speak", "Dog"),
    ("ruby", "speak", "Dog"),
]


@pytest.fixture
def impl_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over the implementations fixture corpus."""
    from src.engine.metrics import MetricsCollector
    from src.engine.redactor import Redactor
    from tests.conftest import _indexed_components, _symbol_index

    repo = tmp_path / "implementations_repo"
    shutil.copytree(FIXTURES_DIR / "implementations", repo)
    comps = _indexed_components(repo, repo / ".context")
    comps["symbol_fqns"] = _symbol_index(comps["db"])
    comps["redactor"] = Redactor()
    comps["metrics_collector"] = MetricsCollector(comps["settings"])
    return comps


def _fqn(comps: dict[str, Any], language: str, parent: str, name: str, index: int = 0) -> str:
    return comps["symbol_fqns"][(language, parent, name)][index]


def _names(result: dict[str, Any]) -> list[str]:
    return [impl["type"]["fqn"].rsplit("::", 1)[-1] for impl in result["implementations"]]


def _call_mcp_tool(comps: dict[str, Any], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from src.mcp.server import MCPServer

    server = MCPServer(comps).build_fastmcp()

    async def _invoke() -> Any:
        return await server.call_tool(name, arguments)

    result = asyncio.run(_invoke())
    text = result.content[0].text if result.content else "{}"
    return json.loads(text)


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    from src.cli.main import main

    previous = sys.argv
    sys.argv = ["code-search", *argv]
    try:
        main()
    except SystemExit:
        pass
    finally:
        sys.argv = previous
    return json.loads(capsys.readouterr().out)


# --- Direct, inherited, and cross-language ----------------------------------


def test_direct_implementation(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    assert result["outcome"] == "resolved"
    dog = next(i for i in result["implementations"] if i["type"]["name"] == "Dog")
    assert dog["relationship"] == "direct"
    assert dog["site"]["inherited"] is False
    assert dog["site"]["file_path"].endswith("shapes.py")
    assert dog["site"]["line_start"] >= 1


def test_inherited_declaration_reported_on_ancestor(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    puppy = next(i for i in result["implementations"] if i["type"]["name"] == "Puppy")
    assert puppy["relationship"] == "indirect"
    assert puppy["site"]["inherited"] is True
    assert puppy["site"]["declaring_type_fqn"].endswith("::AbstractPet")
    assert puppy["site"]["fqn"].endswith("AbstractPet.speak")


def test_inner_class_implementer(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "java", "Animal", "speak")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    assert "Outer.InnerAnimal" in _names(result)


def test_anonymous_class_implementer(impl_comps: dict[str, Any]) -> None:
    """An anonymous class is returned with a navigable identity (spec edge case)."""
    fqn = _fqn(impl_comps, "java", "Animal", "speak")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    assert result["outcome"] == "resolved"
    anon = next(i for i in result["implementations"] if "Anonymous" in i["type"]["name"])
    assert anon["relationship"] == "direct"
    assert anon["type"]["file_path"].endswith("Shapes.java")
    assert anon["type"]["line_start"] >= 1
    assert anon["site"] is not None
    assert anon["site"]["file_path"].endswith("Shapes.java")


@pytest.mark.parametrize("language,method,implementer", _DIRECT_CASES)
def test_cross_language_direct_implementation(
    impl_comps: dict[str, Any], language: str, method: str, implementer: str
) -> None:
    fqn = _fqn(impl_comps, language, "Animal", method)
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    assert result["outcome"] == "resolved", language
    match = next(i for i in result["implementations"] if i["type"]["name"] == implementer)
    assert match["relationship"] == "direct"


# --- Honest no-static outcome -----------------------------------------------


def test_no_static_implementation_is_explicit(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "java", "Repository", "find")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    assert result["outcome"] == "no_static_implementation"
    assert result["implementations"] == []
    assert "runtime-generated implementation may exist" in (result["explanation"] or "")
    not_found = find_implementations(
        impl_comps["symbol_store"], impl_comps["edge_store"], "does.not.Exist"
    )
    assert not_found["outcome"] == "not_found"
    assert result["outcome"] != not_found["outcome"]


# --- Indirect, ambiguous, and cross-surface parity --------------------------


def test_indirect_sub_interface_implementation(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)
    cat = next(i for i in result["implementations"] if i["type"]["name"] == "Cat")
    assert cat["relationship"] == "indirect"
    assert cat["type"]["depth"] > 1
    pet = next(i for i in result["implementations"] if i["type"]["name"] == "Pet")
    assert pet["relationship"] == "direct"
    assert pet["type"]["depth"] == 1


def test_ambiguous_reference_returns_candidates(impl_comps: dict[str, Any]) -> None:
    result = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], "handle")
    assert result["outcome"] == "ambiguous"
    assert result["symbol"] is None
    assert result["implementations"] == []
    assert len(result["candidates"]) >= 2


def test_cross_surface_parity(
    impl_comps: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    engine = find_implementations(impl_comps["symbol_store"], impl_comps["edge_store"], fqn)

    mcp = _call_mcp_tool(impl_comps, "get_implementations", {"symbol": fqn})
    direction = json.loads(
        _call_neighbors_payload(
            impl_comps["symbol_store"],
            impl_comps["edge_store"],
            fqn,
            "implements",
        )
    )
    from src.engine.daemon import QueryDaemon

    daemon = QueryDaemon._do_implementations(impl_comps, {"fqn": fqn})["payload"]
    cli = _run_cli(
        ["implementations", fqn, "--json", f"--context-dir={impl_comps['context_dir']}"],
        capsys,
    )

    expected = _names(engine)
    for surface, payload in (
        ("mcp", mcp),
        ("direction", direction),
        ("daemon", daemon),
        ("cli", cli),
    ):
        assert payload["outcome"] == "resolved", surface
        assert _names(payload) == expected, surface


# --- Cross-module implementations ------------------------------------------


@pytest.fixture
def cross_module_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components where the interface and implementer are in separate modules."""
    from tests.conftest import _indexed_components, _symbol_index

    repo = tmp_path / "cross_module_repo"
    shutil.copytree(FIXTURES_DIR / "implementations_cross_module", repo)
    comps = _indexed_components(repo, repo / ".context")
    comps["symbol_fqns"] = _symbol_index(comps["db"])
    return comps


def test_cross_module_python_implementation(cross_module_comps: dict[str, Any]) -> None:
    """An imported base resolves to its single declared type across modules.

    ``from pkg.animals import Zebra`` expands to the dotted ``pkg.animals.Zebra``
    in the import map, which the indexer cannot match verbatim to the file-path
    FQN; the lone type declaration sharing the leaf name must still be linked.
    """
    fqn = _fqn(cross_module_comps, "python", "Zebra", "trot")
    result = find_implementations(
        cross_module_comps["symbol_store"], cross_module_comps["edge_store"], fqn
    )
    assert result["outcome"] == "resolved"
    plains = next(i for i in result["implementations"] if i["type"]["name"] == "PlainsZebra")
    assert plains["relationship"] == "direct"
    assert plains["site"]["file_path"].endswith("dogs.py")


# --- Audit / redaction ------------------------------------------------------


def test_mcp_audits_dedicated_lookup(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    payload = _call_mcp_tool(impl_comps, "get_implementations", {"symbol": fqn})
    entries = impl_comps["audit_db"].get_entries(query_type="get_implementations")
    assert entries, "the get_implementations tool must write an audit entry"
    assert entries[0]["result_count"] == len(payload["implementations"])
    assert entries[0]["redacted_count"] == 0
    assert "source_code" not in json.dumps(payload)


def test_implements_direction_keeps_traversal_audit(impl_comps: dict[str, Any]) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    _call_mcp_tool(impl_comps, "get_call_neighbors", {"symbol": fqn, "direction": "implements"})
    entries = impl_comps["audit_db"].get_entries(query_type="get_call_neighbors")
    assert entries, "the implements direction keeps the get_call_neighbors audit entry"


def test_cli_audits_dedicated_lookup(
    impl_comps: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fqn = _fqn(impl_comps, "python", "Animal", "speak")
    payload = _run_cli(
        ["implementations", fqn, "--json", f"--context-dir={impl_comps['context_dir']}"],
        capsys,
    )
    entries = impl_comps["audit_db"].get_entries(query_type="get_implementations")
    assert entries
    assert entries[0]["result_count"] == len(payload["implementations"])
    assert entries[0]["redacted_count"] == 0


# --- Re-index after the schema bump ----------------------------------------


def test_stale_index_forces_reindex_and_repopulates_inherits(impl_comps: dict[str, Any]) -> None:
    db = impl_comps["db"]
    with db.write_transaction() as conn:
        conn.execute("UPDATE index_metadata SET value = '12' WHERE key = 'index_version';")
        conn.execute("DELETE FROM graph_edges WHERE edge_type = 'INHERITS';")

    # Simulate startup against a pre-bump index: initialize bumps the version
    # and marks the index stale, which forces the next index run to rebuild.
    db.initialize()

    impl_comps["orchestrator"].index_codebase(
        root_path=impl_comps["repo"], force=False, verbose=False
    )

    with db.connect() as conn:
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()["value"]
        edges = conn.execute(
            "SELECT COUNT(*) AS c FROM graph_edges WHERE edge_type = 'INHERITS';"
        ).fetchone()["c"]
    assert int(version) == 13
    assert edges > 0


# --- Indexing: unresolved external base -------------------------------------


def test_unresolved_external_base_persisted(impl_comps: dict[str, Any]) -> None:
    with impl_comps["db"].connect() as conn:
        row = conn.execute(
            "SELECT e.resolved, e.target_raw, s.fqn FROM graph_edges e "
            "JOIN symbols s ON s.id = e.source_symbol_id "
            "WHERE e.edge_type = 'INHERITS' AND e.resolved = 0 LIMIT 1;"
        ).fetchone()
    assert row is not None
    assert row["target_raw"]
    assert row["fqn"].endswith("::Animal")
