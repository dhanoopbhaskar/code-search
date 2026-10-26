"""Contract tests for the Phase 1 agent-facing graph tools and commands.

These drive the *real* FastMCP server and the *real* argparse handlers over an
indexed fixture, so a schema or handler drift is caught at the transport
boundary rather than only in the engine unit tests.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from fastmcp import FastMCP

from code_search.mcp.server import create_server

_NEW_TOOLS = {
    "get_graph_schema",
    "get_file_outline",
    "search_symbols",
    "find_dead_code",
    "get_architecture",
    "check_index_coverage",
    "detect_changes",
}
_EXISTING_TOOLS = {
    "search",
    "get_symbol_definition",
    "get_call_neighbors",
    "find_related",
    "get_implementations",
    "query_graph",
    "shortest_path",
    "explain_symbol",
    "get_impact",
}


@pytest.fixture
def mcp_comps(indexed_transparency: dict[str, Any]) -> dict[str, Any]:
    """Return the indexed fixture wired with the MCP transport dependencies."""
    from code_search.engine.index_service import IndexChangeDetector
    from code_search.engine.redactor import Redactor
    from code_search.engine.reranking import Reranker

    comps = dict(indexed_transparency)
    comps["redactor"] = Redactor()
    comps["reranker"] = Reranker(comps["db"], comps["session_db"], comps["settings"])
    comps["index_change_detector"] = IndexChangeDetector.from_metadata_store(comps["metadata"])
    return comps


@pytest.fixture
def real_mcp(mcp_comps: dict[str, Any]) -> FastMCP:
    """Return the production FastMCP server for the fixture."""
    return create_server(mcp_comps).build_fastmcp()


def _call(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke one MCP tool and decode its JSON payload."""
    result = asyncio.run(mcp.call_tool(name, arguments))
    assert not result.is_error, f"{name} returned an error: {result.content}"
    return json.loads(result.content[0].text)


@pytest.mark.contract
def test_new_tools_registered_with_existing_tools(real_mcp: FastMCP) -> None:
    """The Phase 1 tools are additive; every pre-existing tool stays registered."""
    names = {tool.name for tool in asyncio.run(real_mcp.list_tools())}
    assert names == _NEW_TOOLS | _EXISTING_TOOLS


@pytest.mark.contract
def test_new_tool_schemas_and_defaults(real_mcp: FastMCP) -> None:
    """The new tools expose the documented arguments and bounded defaults."""
    tools = {tool.name: tool for tool in asyncio.run(real_mcp.list_tools())}

    schema = tools["get_graph_schema"].parameters["properties"]
    assert schema["diagnostics"]["default"] is False
    assert schema["limit"]["default"] == 100
    assert schema["offset"]["default"] == 0

    outline = tools["get_file_outline"].parameters["properties"]
    assert outline["limit"]["default"] == 200
    assert outline["include_docstring"]["default"] is False

    symbols = tools["search_symbols"].parameters["properties"]
    assert symbols["exclude_entry_points"]["default"] is True
    assert symbols["include_connected"]["default"] is False
    assert symbols["limit"]["default"] == 50
    assert symbols["offset"]["default"] == 0

    architecture = tools["get_architecture"].parameters["properties"]
    assert architecture["aspects"]["default"] == "overview"
    assert architecture["top_n"]["default"] == 15
    assert architecture["max_communities"]["default"] == 10

    coverage = tools["check_index_coverage"].parameters["properties"]
    assert coverage["max_rows"]["default"] == 500

    dead_code = tools["find_dead_code"].parameters["properties"]
    assert dead_code["include_entry_points"]["default"] is False
    assert dead_code["include_tests"]["default"] is False
    assert dead_code["limit"]["default"] == 50
    assert dead_code["kinds"]["default"] == "function,method,constructor"

    changes = tools["detect_changes"].parameters["properties"]
    assert changes["scope"]["default"] == "impact"
    assert changes["direction"]["default"] == "inbound"
    assert changes["fixpoint"]["default"] is False
    assert changes["seed_filter"]["default"] == "all"

    # Parity additions on pre-existing tools.
    assert tools["query_graph"].parameters["properties"]["direction"]["default"] == "both"
    assert (
        tools["shortest_path"].parameters["properties"]["edge_types"]["default"] == "CALLS,INHERITS"
    )


@pytest.mark.contract
def test_get_graph_schema_real_payload(real_mcp: FastMCP) -> None:
    """The schema tool reports labels, edge types, coverage, and generation."""
    payload = _call(real_mcp, "get_graph_schema", {})

    assert payload["schema_version"] >= 17
    assert payload["node_labels"]
    assert "CALLS" in payload["edge_types_supported"]
    assert payload["stats"]["total_symbols"] > 0
    assert "complete" in payload["coverage"]
    assert "index_generation" in payload
    assert "freshness" in payload
    assert "absence is not proof of completeness" in payload["note"]


@pytest.mark.contract
def test_get_file_outline_real_payload(real_mcp: FastMCP, mcp_comps: dict[str, Any]) -> None:
    """The outline tool lists a real file in source order."""
    repo = mcp_comps["repo"]
    target = repo / "src" / "main" / "java" / "com" / "example" / "article" / "ArticleService.java"
    payload = _call(real_mcp, "get_file_outline", {"file_path": str(target)})

    assert payload["outcome"] == "resolved"
    assert payload["file_path"].endswith("ArticleService.java")
    assert payload["total"] >= 1
    line_numbers = [entry["line_start"] for entry in payload["symbols"]]
    assert line_numbers == sorted(line_numbers)
    assert payload["truncated"] is False


@pytest.mark.contract
def test_search_symbols_real_payload(real_mcp: FastMCP) -> None:
    """Structural search finds classes by kind and file pattern."""
    payload = _call(
        real_mcp,
        "search_symbols",
        {
            "kind": "class",
            "file_pattern": "*ArticleService.java",
            "include_connected": True,
            "exclude_entry_points": False,
        },
    )

    assert payload["outcome"] == "resolved"
    assert payload["total"] >= 1
    article_service = payload["symbols"][0]
    assert article_service["name"] == "ArticleService"
    assert article_service["kind"] == "class"
    assert set(article_service["degree"]) == {"in", "out", "total"}
    assert "connected" in article_service


@pytest.mark.contract
def test_find_dead_code_real_payload(real_mcp: FastMCP) -> None:
    """The dead-code tool reports candidates and its trust contract."""
    payload = _call(real_mcp, "find_dead_code", {})

    assert payload["outcome"] == "resolved"
    assert isinstance(payload["candidates"], list)
    assert set(payload["edge_types_checked"]) == {
        "CALLS",
        "USAGE",
        "CALL_REFERENCE",
        "REFERENCES",
        "IMPLEMENTS",
        "INHERITS",
    }
    assert "absence is not proof of completeness" in payload["note"]
    assert payload["limit"] == 50


@pytest.mark.contract
def test_get_architecture_real_payload(real_mcp: FastMCP) -> None:
    """The default architecture payload is the bounded overview."""
    payload = _call(real_mcp, "get_architecture", {})

    assert payload["outcome"] == "resolved"
    assert payload["aspects"] == ["overview"]
    assert payload["languages"]
    assert payload["packages"]
    assert "entry_points" in payload
    assert "hotspots" not in payload
    assert "cycles" not in payload


@pytest.mark.contract
def test_check_index_coverage_real_payload(real_mcp: FastMCP, mcp_comps: dict[str, Any]) -> None:
    """Coverage is available for a current-generation index."""
    payload = _call(real_mcp, "check_index_coverage", {})

    assert payload["outcome"] == "resolved"
    assert payload["index_generation"]
    assert isinstance(payload["coverage_complete"], bool)
    assert set(payload["summary"]) == {"requested", "returned", "by_status", "truncated"}
    assert payload["recommended_action"]


@pytest.mark.contract
def test_detect_changes_scope_files_real_payload(
    real_mcp: FastMCP, mcp_comps: dict[str, Any]
) -> None:
    """Scope=files returns the normalized changed set without traversal."""
    target = mcp_comps["repo"] / "src/main/java/com/example/article/ArticleService.java"
    payload = _call(
        real_mcp,
        "detect_changes",
        {"changed_paths": [str(target)], "scope": "files"},
    )

    assert payload["outcome"] == "resolved"
    assert payload["changed_files"] == ["src/main/java/com/example/article/ArticleService.java"]
    assert "impacted" not in payload


@pytest.mark.contract
def test_query_graph_direction_is_reported(real_mcp: FastMCP) -> None:
    """The traversal direction is echoed in the answer stats."""
    payload = _call(
        real_mcp,
        "query_graph",
        {"question": "ArticleService", "depth": 1, "direction": "inbound"},
    )

    assert payload["stats"]["direction"] == "inbound"
    assert payload["stats"]["edge_types"]


@pytest.mark.contract
def test_cli_new_commands_emit_json(
    mcp_comps: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every new CLI command runs through the real handler and emits JSON."""
    from code_search.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_initialize_components", lambda _ctx, **_kwargs: mcp_comps)
    parser = cli_main.build_parser()
    context = str(mcp_comps["context_dir"])
    article = str(
        mcp_comps["repo"]
        / "src"
        / "main"
        / "java"
        / "com"
        / "example"
        / "article"
        / "ArticleService.java"
    )

    invocations = [
        ["schema", "--context-dir", context, "--json"],
        ["outline", article, "--context-dir", context, "--json"],
        [
            "symbols",
            "--kind",
            "class",
            "--include-entry-points",
            "--context-dir",
            context,
            "--json",
        ],
        ["dead-code", "--context-dir", context, "--json"],
        ["coverage", "--scope", "src", "--context-dir", context, "--json"],
        ["map", "--aspects", "overview", "--context-dir", context, "--json"],
        ["affected", article, "--scope", "files", "--context-dir", context, "--json"],
    ]
    for argv in invocations:
        args = parser.parse_args(argv)
        code = args.func(args)
        captured = capsys.readouterr()
        assert code == 0, f"{argv[0]} exited {code}: {captured.err}"
        payload = json.loads(captured.out)
        assert isinstance(payload, dict)
        assert "freshness" in payload, argv[0]

    assert args.command == "affected"
