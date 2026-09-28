from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from fastmcp import FastMCP

from src.engine.graph import read_source_slice
from src.mcp.server import _call_neighbors_payload, _definition_payload

EXPECTED_SEARCH_INPUT = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "default": 10},
        "language": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "include_test_files": {"type": "boolean", "default": False},
        "mode": {"type": "string", "default": "ranked"},
        "content": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "no_model": {"type": "boolean", "default": False},
        "matching": {"type": "string", "default": "all_tokens"},
    },
    "required": ["query"],
}

EXPECTED_SEARCH_OUTPUT_ITEM = {
    "chunk_id": int,
    "file_path": str,
    "line_start": int,
    "line_end": int,
    "content": str,
    "fqn": str,
    "language": str,
    "score": float,
    "bm25_score": (int, float),
    "vector_score": (int, float),
    "is_definition": bool,
    "is_test_file": bool,
    "is_non_canonical": bool,
    "redacted_count": int,
    "below_threshold": bool,
    "relevance_threshold_applied": bool,
    "file_matches": int,
}

EXPECTED_SYMBOL_INPUT = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
    },
    "required": ["symbol"],
}

EXPECTED_SYMBOL_OUTPUT = {
    "found": bool,
    "symbol": dict,
    "parent": (dict, type(None)),
}

EXPECTED_GRAPH_INPUT = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "direction": {"type": "string", "default": "both"},
        "max_depth": {"type": "integer", "default": 1},
        "transitive": {"type": "boolean", "default": False},
    },
    "required": ["symbol"],
}

EXPECTED_GRAPH_OUTPUT = {
    "symbol": dict,
    "callers": list,
    "callees": list,
}

EXPECTED_RELATED_INPUT = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "line_number": {"type": "integer"},
        "limit": {"type": "integer", "default": 5},
    },
    "required": ["file_path", "line_number"],
}

EXPECTED_IMPLEMENTATIONS_INPUT = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
    },
    "required": ["symbol"],
}


def _json_schema_key(key: str, value: Any) -> Any:
    return {"type": "string"} if key == "type" else value


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return schema


def _input_matches_contract(actual: dict[str, Any], contract: dict[str, Any]) -> bool:
    if actual.get("type") != contract.get("type"):
        return False
    if set(actual.get("required", [])) != set(contract.get("required", [])):
        return False
    actual_props = actual.get("properties", {})
    contract_props = contract.get("properties", {})
    if set(actual_props.keys()) != set(contract_props.keys()):
        return False
    for key, expected in contract_props.items():
        actual_type = actual_props[key].get("type")
        expected_type = expected.get("type")
        if actual_type != expected_type:
            return False
    return True


@pytest.fixture
def mcp_server() -> FastMCP:
    mcp: FastMCP = FastMCP("code-search-test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
        content: str | None = None,
        no_model: bool = False,
        matching: str = "all_tokens",
    ) -> str:
        return json.dumps([])

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps({"found": False, "symbol": None, "parent": None})

    @mcp.tool()
    def get_call_neighbors(
        symbol: str,
        direction: str = "both",
        max_depth: int = 1,
        transitive: bool = False,
    ) -> str:
        return json.dumps({"symbol": None, "callers": [], "callees": []})

    @mcp.tool()
    def find_related(
        file_path: str,
        line_number: int,
        limit: int = 5,
    ) -> str:
        return json.dumps([])

    @mcp.tool()
    def get_implementations(symbol: str) -> str:
        return json.dumps(
            {
                "outcome": "resolved",
                "symbol": None,
                "declaring_type": None,
                "implementations": [],
                "candidates": [],
                "explanation": None,
            }
        )

    return mcp


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_tool_schema(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    t = next(t for t in tools if t.name == "search")
    assert _input_matches_contract(t.parameters, EXPECTED_SEARCH_INPUT), (
        f"search input mismatch: {t.parameters}"
    )


EXPECTED_SCOPE_FIELDS: dict[str, Any] = {
    "effective": str,
    "origin": str,
    "intent": str,
    "suggested": (str, type(None)),
    "signal": (str, type(None)),
    "override": str,
}


@pytest.mark.contract
def test_search_response_scope_object_is_additive_and_typed() -> None:
    """The search response carries the documented additive
    ``scope`` object (``effective``/``origin``/``intent``/``suggested``/
    ``signal``/``override``) whose ``effective`` mirrors ``content``."""
    response = {
        "content": "all",
        "scope": {
            "effective": "all",
            "origin": "inferred",
            "intent": "docs",
            "suggested": None,
            "signal": (
                "documentation intent detected; searched with content scope all "
                "inferred from the query"
            ),
            "override": "all",
        },
    }
    scope = response["scope"]
    assert set(scope) == set(EXPECTED_SCOPE_FIELDS), sorted(scope)
    for key, types in EXPECTED_SCOPE_FIELDS.items():
        assert isinstance(scope[key], types), key
    assert scope["effective"] == response["content"]
    assert scope["origin"] in ("explicit", "inferred", "default")
    assert scope["intent"] in ("docs", "config", "neutral")


@pytest.mark.contract
def test_scope_signal_rendered_in_mcp_dialect_not_cli() -> None:
    """The MCP surface renders ``scope.override`` as
    ``content="<scope>"`` so no MCP caller sees a CLI-only flag."""
    scope = {"signal": "configuration excluded; use content scope config", "override": "config"}
    rendered = f'{scope["signal"]} (override with content="{scope["override"]}")'
    assert 'content="config"' in rendered
    assert "--content" not in rendered


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_score_sources_additive_fields() -> None:
    """score_sources carries the additive ranking evidence."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "chunk_id": 42,
                        "file_path": "src/state.ts",
                        "score": 0.74,
                        "is_definition": True,
                        "score_sources": {
                            "bm25": -2.1,
                            "vector": 0.52,
                            "fused": 0.61,
                            "alpha": 0.3,
                            "weights": {"code": 1.0, "boilerplate": 0.65, "resource": 0.35},
                            "rescue": {"tier": "stem_match", "boost": 1.5},
                            "path_boost": None,
                            "embedded_symbol": None,
                            "path_class": "canonical",
                            "reranked": True,
                        },
                    }
                ],
                "freshness": _freshness(),
            }
        )

    result = await mcp.call_tool("search", {"query": "StateManager"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    ss = data["results"][0]["score_sources"]
    for key in ("alpha", "weights", "rescue", "path_boost", "embedded_symbol", "path_class"):
        assert key in ss, f"score_sources missing {key}"
    assert ss["alpha"] == 0.3
    assert ss["rescue"] == {"tier": "stem_match", "boost": 1.5}
    assert ss["path_boost"] is None
    assert ss["embedded_symbol"] is None
    assert ss["path_class"] == "canonical"


@pytest.mark.contract
def test_match_boost_evidence_is_additive(indexed_match_boost: dict[str, Any]) -> None:
    """The match-boost evidence is additive; pre-existing keys are unchanged."""
    envelope = indexed_match_boost["search"].search("README", limit=5, content="docs")
    result = envelope["results"][0]
    sources = result["score_sources"]
    for key in (
        "bm25",
        "vector",
        "fused",
        "alpha",
        "weights",
        "rescue",
        "path_boost",
        "embedded_symbol",
        "declared_rule",
        "path_class",
        "reranked",
        "match_boost",
    ):
        assert key in sources, f"score_sources missing {key}"
    evidence = sources["match_boost"]
    assert evidence is not None
    assert evidence["tier"] == "exact_filename"
    assert evidence["boost"] >= 0.0
    assert 0.0 <= evidence["match_ratio"] <= 1.0


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_tool_schema(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    t = next(t for t in tools if t.name == "get_symbol_definition")
    assert _input_matches_contract(t.parameters, EXPECTED_SYMBOL_INPUT), (
        f"get_symbol_definition input mismatch: {t.parameters}"
    )


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_tool_schema(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    t = next(t for t in tools if t.name == "get_call_neighbors")
    assert _input_matches_contract(t.parameters, EXPECTED_GRAPH_INPUT), (
        f"get_call_neighbors input mismatch: {t.parameters}"
    )


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_tool_transitive_is_additive_boolean_default_false(
    mcp_server: FastMCP,
) -> None:
    """``get_call_neighbors`` gains an additive boolean
    ``transitive`` input defaulting to false; pre-existing inputs keep their
    names and types."""
    tools = await mcp_server.list_tools()
    t = next(tool for tool in tools if tool.name == "get_call_neighbors")
    props = t.parameters["properties"]
    assert props["transitive"]["type"] == "boolean"
    assert props["transitive"]["default"] is False
    assert props["symbol"]["type"] == "string"
    assert props["direction"]["type"] == "string"
    assert props["max_depth"]["type"] == "integer"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_deduplicated_response_shape() -> None:
    """The response carries each caller/callee once at its minimum depth while
    pre-existing fields keep their names/types/meaning."""
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(
        symbol: str,
        direction: str = "both",
        max_depth: int = 1,
        transitive: bool = False,
    ) -> str:
        return json.dumps(
            {
                "outcome": "resolved",
                "symbol": {
                    "fqn": "mod.root",
                    "kind": "function",
                    "file_path": "src/mod.py",
                    "line_start": 1,
                },
                "callers": [
                    {
                        "fqn": "mod.caller",
                        "kind": "function",
                        "file_path": "src/caller.py",
                        "line_start": 10,
                        "source_range": "[10,4,10,20]",
                        "depth": 1,
                        "target_signature": {"arity": 0},
                        "overloads": [],
                    }
                ],
                "callees": [
                    {
                        "fqn": "mod.leaf",
                        "kind": "function",
                        "file_path": "src/leaf.py",
                        "line_start": 3,
                        "target_range": "[5,8,5,25]",
                        "depth": 2,
                        "resolved": True,
                        "target_raw": None,
                        "target_signature": None,
                        "overloads": [],
                    }
                ],
            }
        )

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "mod.root", "transitive": True})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    for key in ("callers", "callees"):
        fqns = [n["fqn"] for n in data[key]]
        assert len(fqns) == len(set(fqns)), f"{key} must be deduplicated"
    for neighbor in data["callees"]:
        for key in ("fqn", "depth", "resolved", "target_raw", "target_signature", "overloads"):
            assert key in neighbor
    assert data["callees"][0]["depth"] == 2


@pytest.mark.contract
@pytest.mark.asyncio
async def test_related_tool_schema(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    t = next(t for t in tools if t.name == "find_related")
    assert _input_matches_contract(t.parameters, EXPECTED_RELATED_INPUT), (
        f"find_related input mismatch: {t.parameters}"
    )


@pytest.mark.contract
@pytest.mark.asyncio
async def test_implementations_tool_schema(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    tool = next(t for t in tools if t.name == "get_implementations")
    assert _input_matches_contract(tool.parameters, EXPECTED_IMPLEMENTATIONS_INPUT), (
        f"get_implementations input mismatch: {tool.parameters}"
    )
    assert tool.parameters["properties"]["symbol"]["type"] == "string"


@pytest.mark.contract
def test_implementations_no_static_explanation(tmp_path: Any) -> None:
    """A resolved interface with no static implementer returns an
    explicit ``no_static_implementation`` explanation and no fabricated entry."""
    from src.engine.config import Settings
    from src.engine.graph import EdgeStore, GraphDatabase
    from src.engine.symbols import SymbolStore
    from src.mcp.server import _implementations_payload

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)
    symbol_store.insert_symbols_batch(
        [
            {
                "fqn": "src/repo.py::Repo",
                "name": "Repo",
                "kind": "interface",
                "file_path": "src/repo.py",
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            },
            {
                "fqn": "src/repo.py::Repo.find",
                "name": "find",
                "kind": "method",
                "file_path": "src/repo.py",
                "line_start": 3,
                "line_end": 4,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": "src/repo.py::Repo",
            },
        ]
    )
    data = json.loads(_implementations_payload(symbol_store, edge_store, "src/repo.py::Repo.find"))
    assert data["outcome"] == "no_static_implementation"
    assert data["implementations"] == []
    assert "runtime-generated implementation may exist" in data["explanation"]


@pytest.mark.contract
def test_graph_implements_direction_returns_implementations(tmp_path: Any) -> None:
    """The ``implements`` direction is an equivalent entry point to the
    shared rule (implementations content, empty callers/callees); every other
    direction is unchanged."""
    from src.engine.config import Settings
    from src.engine.graph import EdgeStore, GraphDatabase
    from src.engine.symbols import SymbolStore

    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "graph.db", settings)
    db.initialize()
    symbol_store = SymbolStore(db, settings)
    edge_store = EdgeStore(db, settings)
    ids = symbol_store.insert_symbols_batch(
        [
            {
                "fqn": "src/i.py::I",
                "name": "I",
                "kind": "interface",
                "file_path": "src/i.py",
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            },
            {
                "fqn": "src/i.py::I.m",
                "name": "m",
                "kind": "method",
                "file_path": "src/i.py",
                "line_start": 3,
                "line_end": 4,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": "src/i.py::I",
            },
            {
                "fqn": "src/a.py::A",
                "name": "A",
                "kind": "class",
                "file_path": "src/a.py",
                "line_start": 1,
                "line_end": 2,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": None,
            },
            {
                "fqn": "src/a.py::A.m",
                "name": "m",
                "kind": "method",
                "file_path": "src/a.py",
                "line_start": 3,
                "line_end": 4,
                "column_start": 0,
                "column_end": 5,
                "language": "java",
                "parent_fqn": "src/a.py::A",
            },
        ]
    )
    edge_store.insert_edges_batch(
        [
            {
                "source_symbol_id": ids["src/a.py::A"],
                "target_symbol_id": ids["src/i.py::I"],
                "edge_type": "INHERITS",
            }
        ]
    )
    implements = json.loads(
        _call_neighbors_payload(symbol_store, edge_store, "src/i.py::I.m", "implements")
    )
    assert [i["type"]["name"] for i in implements["implementations"]] == ["A"]
    assert implements["callers"] == []
    assert implements["callees"] == []
    assert implements["outcome"] == "resolved"

    both = json.loads(_call_neighbors_payload(symbol_store, edge_store, "src/i.py::I.m", "both"))
    assert "implementations" not in both
    assert both["callers"] == []
    assert both["callees"] == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_all_five_tools_registered(mcp_server: FastMCP) -> None:
    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "search",
        "get_symbol_definition",
        "get_call_neighbors",
        "find_related",
        "get_implementations",
    }, f"Expected 5 tools, got {names}"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_tool_output_structure() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "chunk_id": 1,
                        "file_path": "src/test.py",
                        "line_start": 10,
                        "line_end": 35,
                        "content": "def test(): pass",
                        "fqn": "mod.test",
                        "language": "python",
                        "score": 0.89,
                        "bm25_score": 12.5,
                        "vector_score": 0.78,
                        "is_definition": True,
                        "is_test_file": False,
                        "is_non_canonical": False,
                        "redacted_count": 0,
                        "below_threshold": False,
                        "relevance_threshold_applied": True,
                        "file_matches": 1,
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 42.5,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool("search", {"query": "test"})
    assert not result.is_error
    assert len(result.content) > 0
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "results" in data
    assert "freshness" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 1
    item = data["results"][0]
    for key, expected_type in EXPECTED_SEARCH_OUTPUT_ITEM.items():
        assert key in item, f"Missing key: {key}"
        assert isinstance(item[key], expected_type), (
            f"Key {key}: expected {expected_type}, got {type(item[key])}"
        )


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_output_one_result_per_file() -> None:
    """Search output carries at most one entry per file_path, with
    a populated file_matches field on each retained (best) chunk."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        # Two entries with the same file_path would violate the dedup contract.
        return json.dumps(
            {
                "results": [
                    {
                        "chunk_id": 1,
                        "file_path": "db/migration/V1__init_schema.sql",
                        "line_start": 1,
                        "line_end": 35,
                        "content": "INSERT INTO articles VALUES (1);",
                        "fqn": "migration.sql::0",
                        "language": "sql",
                        "score": 0.9,
                        "bm25_score": 10.0,
                        "vector_score": 0.0,
                        "is_definition": False,
                        "is_test_file": False,
                        "is_non_canonical": False,
                        "redacted_count": 0,
                        "below_threshold": False,
                        "relevance_threshold_applied": True,
                        "file_matches": 3,
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 42.5,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool("search", {"query": "INSERT INTO"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    file_paths = [item["file_path"] for item in data["results"]]
    assert len(file_paths) == len(set(file_paths)), "each file must appear at most once"
    for item in data["results"]:
        assert item["file_matches"] >= 1


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_tool_output_structure() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": True,
                "symbol": {
                    "fqn": "mod.Cls.method",
                    "conventional_fqn": None,
                    "name": "method",
                    "kind": "method",
                    "file_path": "src/mod.py",
                    "line_start": 10,
                    "line_end": 20,
                    "column_start": 4,
                    "column_end": 8,
                    "docstring": "doc",
                    "language": "python",
                    "source_code": "def method(self): pass",
                },
                "parent": {"fqn": "mod.Cls", "name": "Cls", "kind": "class"},
                "candidates": [],
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "mod.Cls.method"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert isinstance(data["symbol"], dict)
    symbol = data["symbol"]
    assert symbol["fqn"] == "mod.Cls.method"
    assert symbol["kind"] == "method"
    assert symbol["file_path"] == "src/mod.py"
    assert isinstance(symbol["line_start"], int)
    assert isinstance(symbol["line_end"], int)
    assert isinstance(symbol["column_start"], int)
    assert isinstance(symbol["column_end"], int)
    assert isinstance(symbol["docstring"], str)
    assert symbol["language"] == "python"
    assert symbol["source_code"] == "def method(self): pass"
    assert isinstance(data["parent"], dict) or data["parent"] is None
    assert isinstance(data["candidates"], list)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_tool_output_structure() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(symbol: str, direction: str = "both", max_depth: int = 1) -> str:
        return json.dumps(
            {
                "symbol": {
                    "fqn": "mod.fn",
                    "kind": "function",
                    "file_path": "src/mod.py",
                    "line_start": 5,
                },
                "callers": [
                    {
                        "fqn": "mod.caller",
                        "kind": "function",
                        "file_path": "src/caller.py",
                        "line_start": 10,
                        "call_site_range": "[10,4,10,20]",
                        "depth": 1,
                    }
                ],
                "callees": [
                    {
                        "fqn": "mod.callee",
                        "kind": "function",
                        "file_path": "src/callee.py",
                        "line_start": 3,
                        "call_site_range": "[5,8,5,25]",
                        "depth": 1,
                    }
                ],
            }
        )

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "mod.fn"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["symbol"], dict)
    assert isinstance(data["callers"], list)
    assert isinstance(data["callees"], list)
    for caller in data["callers"]:
        assert all(k in caller for k in ("fqn", "kind", "file_path", "line_start", "depth"))
    for callee in data["callees"]:
        assert all(k in callee for k in ("fqn", "kind", "file_path", "line_start", "depth"))


@pytest.mark.contract
@pytest.mark.asyncio
async def test_related_tool_output_structure() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def find_related(file_path: str, line_number: int, limit: int = 5) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "chunk_id": 2,
                        "file_path": "src/other.py",
                        "line_start": 15,
                        "line_end": 30,
                        "content": "def other(): pass",
                        "fqn": "mod.other",
                        "language": "python",
                        "similarity": 0.85,
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 42.5,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool("find_related", {"file_path": "src/mod.py", "line_number": 10})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data, dict)
    assert "results" in data
    assert "freshness" in data
    if len(data["results"]) > 0:
        item = data["results"][0]
        assert all(
            k in item
            for k in (
                "chunk_id",
                "file_path",
                "line_start",
                "line_end",
                "content",
                "fqn",
                "language",
                "similarity",
            )
        )
        assert isinstance(item["similarity"], (int, float))


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_tool_error_index_not_initialized() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps({"error": "Index not initialized. Run 'code-search index' first."})

    result = await mcp.call_tool("search", {"query": "jwt"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert "error" in data


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_not_found() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps({"found": False, "symbol": None, "parent": None, "candidates": []})

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "nonexistent.sym"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is False
    assert data["symbol"] is None
    assert data["parent"] is None
    assert data["candidates"] == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_call_neighbors_ambiguous_payload_shape() -> None:
    """An ambiguous call-graph name reports candidates, never an error."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(symbol: str, direction: str = "both", max_depth: int = 1) -> str:
        return json.dumps(
            {
                "ambiguous": True,
                "symbol": None,
                "candidates": [
                    {
                        "fqn": (
                            "src/main/java/.../ArticleService.java::"
                            "ArticleService.getBySlug(String)"
                        ),
                        "conventional_fqn": "com.example.service.ArticleService.getBySlug(String)",
                        "name": "getBySlug",
                        "kind": "method",
                        "file_path": "src/main/java/.../ArticleService.java",
                        "line_start": 34,
                        "line_end": 41,
                        "parent_name": "ArticleService",
                    }
                ],
                "callers": [],
                "callees": [],
            }
        )

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "getBySlug"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["ambiguous"] is True
    assert data["symbol"] is None
    assert data["callers"] == []
    assert data["callees"] == []
    assert len(data["candidates"]) >= 1
    cand = data["candidates"][0]
    for key in (
        "fqn",
        "conventional_fqn",
        "name",
        "kind",
        "file_path",
        "line_start",
        "line_end",
        "parent_name",
    ):
        assert key in cand, f"missing candidate key: {key}"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_ambiguous_candidates_shape() -> None:
    """An ambiguous definition name reports matches, never a lie."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": True,
                "ambiguous": True,
                "symbol": None,
                "parent": None,
                "candidates": [
                    {
                        "fqn": "mod.Cls.getBySlug(java.lang.String)",
                        "conventional_fqn": "mod.Cls.getBySlug",
                        "name": "getBySlug",
                        "kind": "method",
                        "file_path": "src/Cls.java",
                        "line_start": 10,
                        "line_end": 12,
                        "parent_name": "Cls",
                    }
                ],
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "getBySlug"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["ambiguous"] is True
    assert data["symbol"] is None
    assert data["parent"] is None
    assert data["candidates"] != []
    cand = data["candidates"][0]
    assert cand["fqn"] == "mod.Cls.getBySlug(java.lang.String)"
    assert cand["name"] == "getBySlug"
    assert cand["kind"] == "method"
    assert cand["file_path"] == "src/Cls.java"
    assert cand["parent_name"] == "Cls"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_near_miss_suggestion_shape() -> None:
    """A near-miss symbol lookup carries candidates with
    ``edit_distance`` and ``suggestion: true`` instead of a silent empty list."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": False,
                "symbol": None,
                "parent": None,
                "candidates": [
                    {
                        "fqn": "src/TokenService.java::TokenService.isTokenValid(String,String)",
                        "conventional_fqn": "com.example.security.TokenService.isTokenValid",
                        "name": "isTokenValid",
                        "kind": "method",
                        "file_path": "src/TokenService.java",
                        "line_start": 48,
                        "line_end": 55,
                        "edit_distance": 1,
                        "suggestion": True,
                    }
                ],
                "suggestion": True,
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "validateToken"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is False
    assert data["suggestion"] is True
    assert data["candidates"] != []
    cand = data["candidates"][0]
    assert cand["edit_distance"] == 1
    assert cand["suggestion"] is True
    assert cand["name"] == "isTokenValid"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_resolved_no_suggestion_flag() -> None:
    """A resolved symbol keeps the unchanged shape (no suggestion noise)."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": True,
                "symbol": {
                    "fqn": "src/TokenService.java::TokenService.isTokenValid(String,String)",
                    "name": "isTokenValid",
                    "kind": "method",
                    "file_path": "src/TokenService.java",
                    "line_start": 48,
                    "line_end": 55,
                    "source_code": "public boolean isTokenValid(...) { }",
                },
                "parent": None,
                "candidates": [],
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "isTokenValid"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["candidates"] == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_symbol_not_found() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(symbol: str, direction: str = "both", max_depth: int = 1) -> str:
        return json.dumps({"symbol": None, "callers": [], "callees": []})

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "nonexistent.sym"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["symbol"] is None
    assert data["callers"] == []
    assert data["callees"] == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_related_no_chunk() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def find_related(file_path: str, line_number: int, limit: int = 5) -> str:
        return json.dumps(
            {
                "error": f"No indexed chunk found at '{file_path}:{line_number}'",
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 42.5,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool(
        "find_related",
        {"file_path": "src/nonexistent.py", "line_number": 10},
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert "error" in data
    assert "freshness" in data
    assert data["freshness"]["stale"] is False


_FRESHNESS_CONTRACT_KEYS = {
    "stale",
    "stale_change_count",
    "modified_files",
    "deleted_files",
    "new_files",
    "index_age_s",
    "index_status",
    "index_root",
    "checked_at",
}


def _freshness(stale: bool = False, change_count: int = 0) -> dict[str, Any]:
    return {
        "stale": stale,
        "stale_change_count": change_count,
        "modified_files": 0,
        "deleted_files": 0,
        "new_files": 0,
        "index_age_s": 42.5,
        "index_status": "ready",
        "index_root": "/repo",
        "checked_at": "2026-08-05T12:00:00.000000Z",
    }


@pytest.mark.contract
def test_search_envelope_carries_vector_health(indexed_semantic_vector: dict[str, Any]) -> None:
    """The search envelope carries a ``vector_health`` field whose
    semantics match the contract — true iff the vector index is populated AND
    the embedding model produced a query vector.

    The semantic fixture indexes real chunks and loads the local model, so a
    healthy layer must report ``vector_health: true`` and per-result
    ``vector_degraded: false`` on a natural-language query.
    """
    search = indexed_semantic_vector["search"]
    envelope = search.search(
        "how long can a user stay signed in before their session token expires",
        limit=10,
    )
    assert "vector_health" in envelope, "search envelope missing vector_health"
    assert isinstance(envelope["vector_health"], bool)
    assert envelope["vector_health"] is True
    assert envelope["results"], "expected results from the semantic fixture"
    for item in envelope["results"]:
        assert item.get("vector_degraded") is False, (
            f"healthy vector layer must not mark result {item.get('chunk_id')} degraded"
        )


@pytest.mark.contract
def test_search_result_semantic_contribution_contract(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """The additive ``vector_retrieved`` / ``semantic_contribution``
    fields, and the clarified truthful ``vector_score`` semantics.

    A zero ``vector_score`` means "no positive semantic retrieval" and must carry
    a non-``semantic`` contribution label; a retrieved chunk reports its actual
    positive similarity and the ``semantic`` label. Existing fields and the
    ``score_sources`` keys stay present (additive-only change).
    """
    search = indexed_semantic_vector["search"]
    envelope = search.search(
        "how long can a user stay signed in before their session token expires",
        limit=10,
    )
    assert envelope["results"], "expected results from the semantic fixture"
    allowed = {"semantic", "lexical_only", "deferred", "unavailable"}
    for item in envelope["results"]:
        assert isinstance(item["vector_retrieved"], bool)
        assert item["semantic_contribution"] in allowed
        if item["vector_retrieved"]:
            assert item["semantic_contribution"] == "semantic"
            assert item["vector_score"] > 0.0
        else:
            assert item["vector_score"] == 0.0
        for key in ("chunk_id", "file_path", "score", "bm25_score", "vector_score"):
            assert key in item, f"missing existing field {key}"
        score_sources = item.get("score_sources")
        if score_sources is not None:
            assert {"bm25", "vector", "fused", "weights", "reranked"} <= set(score_sources)
            assert score_sources["vector"] == item["vector_score"]


@pytest.mark.contract
def test_find_related_envelope_carries_vector_health(
    indexed_semantic_vector: dict[str, Any],
) -> None:
    """The ``find_related`` envelope carries ``vector_health`` and
    an unindexed location returns the clear non-crashing error.

    The semantic fixture has indexed chunks and a loaded local model, so a
    query anchored on a real file must report ``vector_health: true`` with a
    non-empty related set; a path outside the index must yield the ``error``
    status without raising.
    """
    from src.mcp.server import _find_related_payload

    comps = indexed_semantic_vector
    repo = comps["repo"]
    session_java = (
        repo
        / "src"
        / "main"
        / "java"
        / "com"
        / "example"
        / "semvec"
        / "session"
        / "SessionWindowPolicy.java"
    )
    payload = _find_related_payload(comps, str(session_java), 9, 5)
    data = json.loads(payload)
    assert "vector_health" in data, "find_related envelope missing vector_health"
    assert data["vector_health"] is True
    assert data["results"], "expected a non-empty related set from the semantic fixture"
    for item in data["results"]:
        assert all(
            k in item
            for k in (
                "chunk_id",
                "file_path",
                "line_start",
                "line_end",
                "content",
                "fqn",
                "language",
                "similarity",
            )
        )

    missing_payload = _find_related_payload(comps, str(repo / "not_indexed.py"), 1, 5)
    missing_data = json.loads(missing_payload)
    assert "error" in missing_data, "unindexed location must return a clear error"
    assert "No indexed chunk found" in missing_data["error"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_freshness_signal_shape_present_in_all_tools() -> None:
    """Every tool response carries the full freshness signal shape."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps({"results": [], "freshness": _freshness(stale=True, change_count=3)})

    @mcp.tool()
    def find_related(file_path: str, line_number: int, limit: int = 5) -> str:
        return json.dumps({"results": [], "freshness": _freshness()})

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": False,
                "symbol": None,
                "parent": None,
                "candidates": [],
                "freshness": _freshness(),
            }
        )

    @mcp.tool()
    def get_call_neighbors(symbol: str, direction: str = "both", max_depth: int = 1) -> str:
        return json.dumps(
            {
                "symbol": None,
                "callers": [],
                "callees": [],
                "freshness": _freshness(),
            }
        )

    for tool_name, args in [
        ("search", {"query": "jwt"}),
        ("find_related", {"file_path": "src/mod.py", "line_number": 10}),
        ("get_symbol_definition", {"symbol": "x"}),
        ("get_call_neighbors", {"symbol": "x"}),
    ]:
        result = await mcp.call_tool(tool_name, args)
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert "freshness" in data, f"tool {tool_name} lacks freshness"
        assert set(data["freshness"].keys()) == _FRESHNESS_CONTRACT_KEYS, (
            f"tool {tool_name} freshness shape: {set(data['freshness'].keys())}"
        )
        assert isinstance(data["freshness"]["stale"], bool)
        assert isinstance(data["freshness"]["stale_change_count"], int)
        assert isinstance(data["freshness"]["index_status"], str)
        assert data["freshness"]["checked_at"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_output_carries_freshness() -> None:
    """A resolved symbol keeps its fields and gains top-level freshness."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": True,
                "symbol": {
                    "fqn": "mod.fn",
                    "name": "fn",
                    "kind": "function",
                    "file_path": "src/mod.py",
                    "line_start": 5,
                    "line_end": 9,
                },
                "parent": None,
                "candidates": [],
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 10.0,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "mod.fn"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["symbol"]["fqn"] == "mod.fn"
    assert data["freshness"]["index_status"] == "ready"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_graph_output_carries_freshness() -> None:
    """Call-neighbor fields are untouched and freshness is added."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(symbol: str, direction: str = "both", max_depth: int = 1) -> str:
        return json.dumps(
            {
                "symbol": {"fqn": "mod.fn", "kind": "function", "file_path": "src/mod.py"},
                "callers": [],
                "callees": [],
                "freshness": {
                    "stale": False,
                    "stale_change_count": 0,
                    "modified_files": 0,
                    "deleted_files": 0,
                    "new_files": 0,
                    "index_age_s": 10.0,
                    "index_status": "ready",
                    "index_root": "/repo",
                    "checked_at": "2026-08-05T12:00:00.000000Z",
                },
            }
        )

    result = await mcp.call_tool("get_call_neighbors", {"symbol": "mod.fn"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert isinstance(data["callers"], list)
    assert isinstance(data["callees"], list)
    assert data["freshness"]["stale"] is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_tool_parameter_defaults() -> None:
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "limit": limit,
                "language": language,
                "include_test_files": include_test_files,
            }
        )

    result = await mcp.call_tool("search", {"query": "test"})
    data = json.loads(result.content[0].text)
    assert data["limit"] == 10
    assert data["language"] is None
    assert data["include_test_files"] is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_envelope_totals_and_truncation() -> None:
    """total_matches/truncated present; result_limit_capped retained."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [{"chunk_id": 1}],
                "total_matches": 13,
                "truncated": True,
                "result_limit_capped": True,
            }
        )

    result = await mcp.call_tool("search", {"query": "@Transactional readOnly = true"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["total_matches"] == 13
    assert data["truncated"] is True
    assert data["result_limit_capped"] is True
    assert len(data["results"]) == 1


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_envelope_present_when_uncapped() -> None:
    """total_matches/truncated are always present, even when results are short."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps({"results": [{"chunk_id": 1}], "total_matches": 1, "truncated": False})

    result = await mcp.call_tool("search", {"query": "token"})
    data = json.loads(result.content[0].text)
    assert data["total_matches"] == 1
    assert data["truncated"] is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_envelope_ranked_uses_best_effort_not_complete() -> None:
    """Ranked envelopes carry total_matches plus best_effort and must
    never claim complete enumeration."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [{"chunk_id": 1}],
                "total_matches": 3,
                "truncated": False,
                "best_effort": True,
            }
        )

    result = await mcp.call_tool("search", {"query": "token"})
    data = json.loads(result.content[0].text)
    assert data["total_matches"] == 3
    assert data["best_effort"] is True
    assert "complete" not in data
    assert "total_count" not in data


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_envelope_exhaustive_uses_total_count() -> None:
    """Exhaustive/enumerate envelopes report the exact total_count with
    a truthful complete flag and excluded paths when structural parsing
    skipped part of the corpus."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [{"chunk_id": 1}],
                "total_count": 7,
                "truncated": False,
                "complete": False,
                "excluded": ["src/Broken.java"],
                "best_effort": False,
            }
        )

    result = await mcp.call_tool("search", {"query": "all controllers"})
    data = json.loads(result.content[0].text)
    assert data["total_count"] == 7
    assert data["complete"] is False
    assert data["excluded"] == ["src/Broken.java"]
    assert "total_matches" not in data


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_exhaustive_item_shape() -> None:
    """Exhaustive result items carry file_path/line_number/line_content."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
    ) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "file_path": "src/security/SecurityConfig.java",
                        "line_number": 42,
                        "line_content": "  @PreAuthorize(\"hasRole('ADMIN')\")",
                    }
                ],
                "mode": "exhaustive",
                "complete": True,
                "total_count": 17,
                "confidence": "high",
            }
        )

    result = await mcp.call_tool("search", {"query": "PreAuthorize", "mode": "exhaustive"})
    data = json.loads(result.content[0].text)
    assert data["mode"] == "exhaustive"
    assert data["total_count"] == 17
    assert data["complete"] is True
    item = data["results"][0]
    assert set(item) == {"file_path", "line_number", "line_content"}, f"got {item}"
    assert item["file_path"] == "src/security/SecurityConfig.java"
    assert item["line_number"] == 42
    assert item["line_content"] == "  @PreAuthorize(\"hasRole('ADMIN')\")"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_enumerate_item_shape() -> None:
    """Enumerate result items carry fqn/file_path/kind."""
    mcp = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
    ) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "fqn": "com.example.ArticleController",
                        "file_path": "src/article/ArticleController.java",
                        "kind": "class",
                    }
                ],
                "mode": "enumerate",
                "complete": True,
                "total_count": 8,
                "confidence": "high",
            }
        )

    result = await mcp.call_tool("search", {"query": "all controllers", "mode": "enumerate"})
    data = json.loads(result.content[0].text)
    assert data["mode"] == "enumerate"
    assert data["total_count"] == 8
    assert data["complete"] is True
    item = data["results"][0]
    assert set(item) == {"fqn", "file_path", "kind"}, f"got {item}"
    assert item["fqn"] == "com.example.ArticleController"
    assert item["file_path"] == "src/article/ArticleController.java"
    assert item["kind"] == "class"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_definition_not_found_negative_lookup() -> None:
    """NonexistentService.fooBar -> found false, symbol null, no error."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps({"found": False, "symbol": None, "parent": None, "candidates": []})

    for query in ("NonexistentService.fooBar", "Not.A.(Symbol", ""):
        result = await mcp.call_tool("get_symbol_definition", {"symbol": query})
        assert not result.is_error, f"query {query!r} must not error"
        data = json.loads(result.content[0].text)
        assert data["found"] is False
        assert data["symbol"] is None


@pytest.mark.contract
@pytest.mark.asyncio
async def test_definition_resolution_unregressed() -> None:
    """An existing definition still resolves found true."""
    mcp = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        return json.dumps(
            {
                "found": True,
                "symbol": {
                    "fqn": "com.example.TokenService.generateToken(String)",
                    "name": "generateToken",
                    "signature": {"arity": 1, "param_types": ["String"], "normalized": "string"},
                },
                "parent": {"name": "TokenService"},
                "candidates": [],
            }
        )

    result = await mcp.call_tool("get_symbol_definition", {"symbol": "TokenService.generateToken"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["found"] is True
    assert data["symbol"]["signature"]["arity"] == 1


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_schema_accepts_content_and_no_model() -> None:
    """The ``search`` tool schema accepts the ``content``
    scope and ``no_model`` toggle with the shared defaults from the
    surface-parity table.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
        content: str = "all",
        no_model: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [],
                "content": content,
                "matching_semantics": "all_tokens",
                "query_time_ms": 1.2,
            }
        )

    tools = await mcp.list_tools()
    t = next(tool for tool in tools if tool.name == "search")
    props = t.parameters["properties"]
    assert "content" in props
    assert props["content"]["default"] == "all"
    assert "no_model" in props
    assert props["no_model"]["type"] == "boolean"
    assert props["no_model"]["default"] is False

    result = await mcp.call_tool("search", {"query": "q", "content": "config", "no_model": True})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["content"] == "config"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_ranked_item_carries_content_type_and_borderline() -> None:
    """Ranked search results carry ``content_type``
    and the always-present ``borderline`` tag.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
        content: str = "all",
        no_model: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "chunk_id": 1,
                        "file_path": "src/main/resources/application-dev.properties",
                        "content_type": "config",
                        "confidence": 0.1,
                        "confidence_band": "low",
                        "borderline": True,
                    }
                ],
                "total_matches": 1,
                "truncated": False,
                "mode": "ranked",
                "content": content,
                "matching_semantics": "all_tokens",
                "query_time_ms": 1.2,
            }
        )

    result = await mcp.call_tool("search", {"query": "pool settings", "content": "config"})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    item = data["results"][0]
    assert item["content_type"] == "config"
    assert item["borderline"] is True


@pytest.mark.contract
@pytest.mark.asyncio
async def test_search_envelope_carries_content_and_matching_semantics_and_query_time() -> None:
    """Every search envelope carries the
    applied ``content`` scope, the ``matching_semantics`` label, and
    ``query_time_ms`` — ranked and exhaustive alike.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def search(
        query: str,
        limit: int = 10,
        language: str | None = None,
        include_test_files: bool = False,
        mode: str = "ranked",
        content: str = "all",
        no_model: bool = False,
    ) -> str:
        return json.dumps(
            {
                "results": [],
                "mode": mode,
                "content": content,
                "matching_semantics": "all_tokens" if mode == "ranked" else "literal",
                "total_matches": 0,
                "truncated": False,
                "query_time_ms": 3.4 if mode == "ranked" else 5.6,
            }
        )

    for mode, query_time in (("ranked", 3.4), ("exhaustive", 5.6)):
        result = await mcp.call_tool("search", {"query": "q", "mode": mode})
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert data["content"] == "all"
        assert "matching_semantics" in data
        assert data["query_time_ms"] == query_time


@pytest.mark.contract
@pytest.mark.asyncio
async def test_find_related_response_carries_status_label() -> None:
    """``find_related`` responses carry the ``status`` label
    (``cross_file``/``same_file_only``/``empty``) and ``query_time_ms``.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def find_related(
        file_path: str,
        line_number: int,
        limit: int = 5,
    ) -> str:
        return json.dumps(
            {
                "results": [{"chunk_id": 17, "file_path": "src/Other.java", "similarity": 0.71}],
                "vector_health": True,
                "status": "cross_file",
                "query_time_ms": 4.1,
            }
        )

    result = await mcp.call_tool("find_related", {"file_path": "src/A.java", "line_number": 42})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["status"] == "cross_file"
    assert data["query_time_ms"] == 4.1


@pytest.mark.contract
@pytest.mark.asyncio
async def test_symbol_definition_carries_overloads_and_ambiguous() -> None:
    """``get_symbol_definition`` responses carry the full
    ``overloads`` set and the ``ambiguous`` flag; a single declaration never
    claims ambiguity.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def get_symbol_definition(symbol: str) -> str:
        overloaded = symbol.endswith("save")
        return json.dumps(
            {
                "found": True,
                "ambiguous": overloaded,
                "symbol": {"fqn": "com.example.ArticleService.save", "signature": "save(Article)"},
                "overloads": (
                    [
                        {"fqn": "com.example.ArticleService.save", "signature": "save(Article)"},
                        {
                            "fqn": "com.example.ArticleService.save",
                            "signature": "save(Article, boolean)",
                        },
                    ]
                    if overloaded
                    else []
                ),
                "query_time_ms": 1.0,
            }
        )

    overloaded = await mcp.call_tool("get_symbol_definition", {"symbol": "ArticleService.save"})
    assert not overloaded.is_error
    data = json.loads(overloaded.content[0].text)
    assert data["ambiguous"] is True
    assert len(data["overloads"]) == 2
    assert data["query_time_ms"] == 1.0

    single = await mcp.call_tool("get_symbol_definition", {"symbol": "ArticleService.load"})
    assert not single.is_error
    data = json.loads(single.content[0].text)
    assert data["ambiguous"] is False
    assert data["overloads"] == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_call_neighbors_carry_resolved_and_target_raw() -> None:
    """Call-graph edges carry ``resolved`` and, for
    unresolved/external references, the raw callee text ``target_raw``.
    """
    mcp: FastMCP = FastMCP("test")

    @mcp.tool()
    def get_call_neighbors(
        symbol: str,
        direction: str = "both",
        max_depth: int = 1,
    ) -> str:
        return json.dumps(
            {
                "symbol": {"fqn": "com.example.ArticleService.save"},
                "edges": [
                    {
                        "source": "com.example.ArticleService.save",
                        "target": "com.example.ArticleRepository.save",
                        "edge_type": "CALLS",
                        "resolved": True,
                    },
                    {
                        "source": "com.example.ArticleService.save",
                        "target_raw": "repository.save(article)",
                        "edge_type": "CALLS",
                        "resolved": False,
                    },
                ],
                "direction": "both",
                "query_time_ms": 2.0,
            }
        )

    result = await mcp.call_tool(
        "get_call_neighbors", {"symbol": "com.example.ArticleService.save"}
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    resolved = [e for e in data["edges"] if e["resolved"] is True]
    unresolved = [e for e in data["edges"] if e["resolved"] is False]
    assert len(resolved) == 1
    assert resolved[0]["target"] == "com.example.ArticleRepository.save"
    assert len(unresolved) == 1
    assert unresolved[0]["target_raw"] == "repository.save(article)"
    assert data["query_time_ms"] == 2.0


@pytest.mark.contract
def test_calibrated_confidence_preserves_result_contract(
    indexed_relevance: dict[str, Any],
) -> None:
    """Calibration keeps the result fields and their invariants intact.

    The recalibrated ``confidence``/``confidence_band`` values must still honour
    the existing contract: the field set is unchanged, the score stays in
    ``[0, 1]``, and ``low_confidence == borderline == (band == "low")``.
    """
    results = indexed_relevance["search"].search("getArticle", limit=10)["results"]
    assert results, "the fixture query must return results"
    required = {"confidence", "confidence_band", "low_confidence", "borderline", "role"}
    for result in results:
        assert required <= set(result), result
        assert 0.0 <= result["confidence"] <= 1.0, result
        assert result["confidence_band"] in ("high", "medium", "low"), result
        assert result["low_confidence"] == (result["confidence_band"] == "low"), result
        assert result["borderline"] == result["low_confidence"], result


@pytest.fixture
def resolution_contract_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed transparency fixture with a redactor for the resolution contract."""
    from src.engine.redactor import Redactor
    from tests.conftest import FIXTURES_DIR, _indexed_components

    repo = tmp_path / "transparency_contract_repo"
    shutil.copytree(FIXTURES_DIR / "transparency", repo)
    comps = _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})
    comps["redactor"] = Redactor()
    return comps


@pytest.mark.contract
def test_resolution_envelope_additive_fields_and_redaction_unchanged(
    resolution_contract_comps: dict[str, Any],
) -> None:
    """``outcome``/``evidence``/``deprecated`` are additive; the rest holds.

    Pre-existing payload fields keep their names, types, and meaning, the
    ``source_code`` redaction path is unchanged, and the audit entry type is
    unchanged.
    """
    comps = resolution_contract_comps
    store = comps["symbol_store"]
    redactor = comps["redactor"]

    ambiguous = json.loads(
        _definition_payload(store, redactor, "ArticleService.save", comps.get("freshness"))
    )
    assert ambiguous["found"] is True
    assert ambiguous["ambiguous"] is True
    assert ambiguous["symbol"] is None
    assert isinstance(ambiguous["candidates"], list) and ambiguous["candidates"]
    assert isinstance(ambiguous["overloads"], list)
    assert ambiguous["outcome"] == "ambiguous"
    for candidate in ambiguous["candidates"]:
        assert isinstance(candidate["evidence"], list) and candidate["evidence"]
        assert isinstance(candidate["deprecated"], bool)
        for key in (
            "fqn",
            "conventional_fqn",
            "name",
            "kind",
            "file_path",
            "line_start",
            "line_end",
        ):
            assert key in candidate

    resolved = json.loads(
        _definition_payload(store, redactor, "ArticleService.delete", comps.get("freshness"))
    )
    assert resolved["found"] is True
    assert resolved["outcome"] == "resolved"
    symbol = resolved["symbol"]
    assert symbol is not None and symbol["source_code"]
    for key in (
        "fqn",
        "conventional_fqn",
        "name",
        "kind",
        "file_path",
        "line_start",
        "line_end",
        "column_start",
        "column_end",
        "language",
        "source_code",
    ):
        assert key in symbol
    raw = read_source_slice(symbol["file_path"], symbol["line_start"], symbol["line_end"])
    redacted, _count = redactor.redact(raw)
    assert symbol["source_code"] == redacted

    neighbors = json.loads(
        _call_neighbors_payload(
            store, comps["edge_store"], "ArticleService.save", "both", 1, comps.get("freshness")
        )
    )
    assert neighbors["outcome"] == "ambiguous"
    assert neighbors["candidates"]

    comps["audit_db"].write_entry(
        query_type="get_symbol_definition",
        query_summary="ArticleService.delete",
        result_count=1,
        duration_ms=1,
        redacted_count=0,
    )
    entries = comps["audit_db"].get_entries(query_type="get_symbol_definition")
    assert any(entry["query_type"] == "get_symbol_definition" for entry in entries)
