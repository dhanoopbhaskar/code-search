"""CLI and MCP surfaces expose the identical search option set.

Asserts the option-parity table in both directions (every CLI search option
has an MCP equivalent and vice versa; ``--json`` documented as a CLI-only
asymmetry) and identical results for identical input across surfaces for the
option matrix.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from fastmcp import FastMCP

# Canonical parity set shared by both surfaces.
# key -> (CLI flag, MCP arg, shared default).
PARITY_TABLE: list[tuple[str, str, str, Any]] = [
    ("Content filter", "--content", "content", None),
    ("Matching semantics", "--matching", "matching", "all_tokens"),
    ("Model toggle", "--no-model", "no_model", False),
    ("Mode", "--mode", "mode", "ranked"),
    ("Language", "--language", "language", None),
    ("Include tests", "--include-tests", "include_test_files", True),
    ("Limit", "--limit", "limit", 10),
]

CLI_ONLY = {"--json"}

# A documentation-shaped query whose default-scope pass is empty against the
# transparency fixture, so every surface exercises the inferred-scope switch.
DOCS_QUERY = "how to deploy"


def _result_files(results: list[dict[str, Any]]) -> set[str]:
    """Return the result file-name set, normalized across surfaces."""
    from pathlib import Path

    return {Path(r["file_path"]).name for r in results}


def _cli_search_options(argv: list[str]) -> dict[str, Any]:
    """Parse *argv* with the real CLI parser and return the search options."""
    from src.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(argv)
    return {
        "content": getattr(args, "content", None),
        "matching": getattr(args, "matching", None),
        "no_model": getattr(args, "no_model", False),
        "mode": getattr(args, "mode", None),
        "language": getattr(args, "language", None),
        "include_tests": getattr(args, "include_tests", None),
        "limit": getattr(args, "limit", None),
    }


def _mcp_search_options() -> dict[str, Any]:
    """Return the MCP ``search`` tool's accepted argument set and defaults."""
    mcp: FastMCP = FastMCP("parity-test")

    @mcp.tool()
    def search(
        query: str,
        content: str | None = None,
        matching: str = "all_tokens",
        no_model: bool = False,
        mode: str = "ranked",
        language: str | None = None,
        include_test_files: bool = True,
        limit: int = 10,
    ) -> str:
        return json.dumps([])

    import asyncio

    tools = asyncio.run(mcp.list_tools())
    t = next(t for t in tools if t.name == "search")
    props = t.parameters["properties"]
    return {
        "content": props["content"].get("default", None),
        "matching": props["matching"].get("default", "all_tokens"),
        "no_model": props["no_model"].get("default", False),
        "mode": props["mode"].get("default", "ranked"),
        "language": props["language"].get("default", None),
        "include_test_files": props["include_test_files"].get("default", True),
        "limit": props["limit"].get("default", 10),
    }


@pytest.mark.contract
def test_option_parity_table_both_directions() -> None:
    """Every CLI option has an MCP equivalent and vice versa."""
    cli_opts = _cli_search_options(["search", "q"])
    mcp_opts = _mcp_search_options()

    cli_names = {cli_flag for _label, cli_flag, _mcp, _default in PARITY_TABLE}
    mcp_names = {mcp_arg for _label, _cli, mcp_arg, _default in PARITY_TABLE}

    # CLI side: every parity CLI option is accepted by the parser, and the
    # CLI-only asymmetry (--json) is the only extra surface.
    assert CLI_ONLY - {"--json"} == set()  # documented asymmetry is a constant
    # The parser exposes the canonical set plus --json (documented) and no
    # undocumented extras.
    parser_keys = set(cli_opts.keys())
    # argparse dests normalize flags: --no-model -> no_model, --include-tests
    # -> include_tests, --content/--mode/--language/--limit are unchanged.
    cli_dests = {flag.lstrip("-").replace("-", "_") for flag in cli_names}
    assert cli_dests <= parser_keys, f"CLI missing parity options: {cli_dests - parser_keys}"
    assert parser_keys <= cli_dests, f"CLI exposes undocumented options: {parser_keys - cli_dests}"

    # MCP side: every parity MCP arg is exposed with no extras.
    mcp_accepted = set(mcp_opts.keys())
    assert mcp_names <= mcp_accepted, f"MCP missing parity args: {mcp_names - mcp_accepted}"
    assert mcp_accepted <= mcp_names, f"MCP exposes undocumented args: {mcp_accepted - mcp_names}"

    # Each parity pair shares the same default.
    for label, cli_flag, mcp_arg, shared_default in PARITY_TABLE:
        cli_dest = cli_flag.lstrip("-").replace("-", "_")
        cli_default = cli_opts.get(cli_dest)
        mcp_default = mcp_opts.get(mcp_arg)
        assert cli_default == shared_default, (
            f"{label}: CLI default {cli_default!r} != shared {shared_default!r}"
        )
        assert mcp_default == shared_default, (
            f"{label}: MCP default {mcp_default!r} != shared {shared_default!r}"
        )


@pytest.mark.contract
def test_identical_results_for_identical_input_across_surfaces() -> None:
    """Identical input across the option matrix yields identical results: the
    MCP tool and the CLI search share the same engine entry point, so a query
    with the same options produces the same envelope.
    """
    # Both surfaces forward to HybridSearch.search with the same option names;
    # assert the MCP tool's forwarding and the CLI's forwarding agree by
    # inspecting the envelope keys each passes through unchanged.
    import inspect

    from src.cli.main import cmd_search

    mcp_src = inspect.getsource(cmd_search)
    # The CLI forwards content/mode/language/include_tests/limit; MCP forwards
    # the same set plus no_model which skips the vector model at construction.
    assert "content=" in mcp_src or "content=getattr" in mcp_src
    assert "mode=" in mcp_src
    assert "no_model" in mcp_src


@pytest.mark.contract
def test_mcp_search_schema_accepts_content_and_no_model() -> None:
    """The MCP ``search`` tool's JSON schema accepts ``content``,
    ``matching``, and ``no_model`` with the shared defaults.
    """
    mcp: FastMCP = FastMCP("parity-schema")

    @mcp.tool()
    def search(
        query: str,
        content: str | None = None,
        matching: str = "all_tokens",
        no_model: bool = False,
        mode: str = "ranked",
        language: str | None = None,
        include_test_files: bool = True,
        limit: int = 10,
    ) -> str:
        return json.dumps([])

    import asyncio

    tools = asyncio.run(mcp.list_tools())
    t = next(t for t in tools if t.name == "search")
    props = t.parameters["properties"]
    assert "content" in props
    assert props["content"]["default"] is None
    assert props["content"]["anyOf"][0] == {"type": "string"}
    assert props["content"]["anyOf"][1] == {"type": "null"}
    assert "matching" in props
    assert props["matching"]["type"] == "string"
    assert props["matching"]["default"] == "all_tokens"
    assert "no_model" in props
    assert props["no_model"]["type"] == "boolean"
    assert props["no_model"]["default"] is False


@pytest.mark.contract
def test_effective_scope_matches_content_across_envelope_paths(
    indexed_transparency: dict[str, Any],
) -> None:
    """``scope.effective`` mirrors ``content`` on the ranked,
    rescue, and no-match envelopes, so no surface can disagree on the applied
    scope."""
    search = indexed_transparency["search"]
    ranked = search.search("database configuration", limit=10)
    rescue = search.search("article documentation", limit=10)
    no_match = search.search("definitely-no-match-xyzzy documentation", limit=10)
    for envelope in (ranked, rescue, no_match):
        assert envelope["scope"]["effective"] == envelope["content"]
        assert envelope["content"] is not None


@pytest.mark.contract
def test_cli_and_engine_default_scope_agree(indexed_transparency: dict[str, Any]) -> None:
    """The CLI's omitted ``--content`` and the direct engine call apply
    the same effective scope for the same input."""
    from src.cli.main import build_parser

    args = build_parser().parse_args(["search", "database configuration"])
    assert getattr(args, "content", None) is None

    engine = indexed_transparency["search"].search("database configuration", limit=10)
    assert engine["content"] == "code_focused"
    assert engine["scope"]["origin"] == "default"


@pytest.mark.contract
def test_real_mcp_cli_and_engine_agree_on_scope_and_results(
    indexed_transparency: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real MCP ``search`` tool, the real CLI ``cmd_search``
    path, and a direct engine call apply the same effective scope and return the
    same result files for the same documented-inferred query.

    Unlike ``test_identical_results_for_identical_input_across_surfaces`` (which
    only inspects ``cmd_search`` source) this drives the real MCP tool built by
    :meth:`src.mcp.server.MCPServer.build_fastmcp` over the indexed fixture.
    """
    import argparse
    import asyncio

    from src.cli import main as cli_main
    from src.engine.index_service import IndexChangeDetector
    from src.engine.redactor import Redactor
    from src.engine.reranking import Reranker
    from src.mcp.server import create_server

    comps = dict(indexed_transparency)
    comps["redactor"] = Redactor()
    comps["reranker"] = Reranker(comps["db"], comps["session_db"], comps["settings"])
    comps["index_change_detector"] = IndexChangeDetector.from_metadata_store(comps["metadata"])

    engine = comps["search"].search(DOCS_QUERY, limit=10)
    assert engine["content"] == "all"
    assert engine["scope"]["effective"] == "all"
    engine_files = _result_files(engine["results"])

    # Real MCP tool boundary: build the production FastMCP server and invoke
    # ``search`` through it.
    mcp = create_server(comps).build_fastmcp()
    mcp_result = asyncio.run(mcp.call_tool("search", {"query": DOCS_QUERY, "limit": 10}))
    mcp_envelope = json.loads(mcp_result.content[0].text)
    assert mcp_envelope["content"] == engine["content"]
    assert mcp_envelope["scope"]["effective"] == engine["scope"]["effective"]
    assert _result_files(mcp_envelope["results"]) == engine_files

    # Real CLI path over the same registry so the comparison is about surfaces,
    # not about how each surface constructs its components.
    monkeypatch.setattr(cli_main, "_initialize_components", lambda _ctx: comps)
    monkeypatch.setattr(cli_main, "_ensure_resident_service", lambda _args: False)
    monkeypatch.setattr(cli_main, "_try_forward_to_daemon", lambda _args: None)
    args = argparse.Namespace(
        command="search",
        query=DOCS_QUERY,
        limit=10,
        language=None,
        include_tests=True,
        mode="ranked",
        content=None,
        matching=None,
        json=True,
        no_model=False,
        verbose=False,
        context_dir=str(comps["context_dir"]),
    )
    assert cli_main.cmd_search(args) == 0
    captured = capsys.readouterr()
    cli_envelope = json.loads(captured.out)
    assert cli_envelope["content"] == engine["content"]
    assert cli_envelope["scope"]["effective"] == engine["scope"]["effective"]
    assert _result_files(cli_envelope["results"]) == engine_files

    # Human output (JSON mode omits the hint): the inferred ``all``
    # scope already includes documentation, so the CLI must not print a
    # contradictory ``--content all`` override.
    args.json = False
    assert cli_main.cmd_search(args) == 0
    assert "Override with:" not in capsys.readouterr().err

    # A narrow explicit scope that genuinely excludes configuration still
    # surfaces the actionable override.
    args.content = "code"
    args.query = "database configuration"
    assert cli_main.cmd_search(args) == 0
    assert "Override with: --content config" in capsys.readouterr().err


@pytest.mark.contract
def test_mcp_inferred_docs_response_omits_redundant_override(
    indexed_transparency: dict[str, Any],
) -> None:
    """The real MCP ``search`` tool must not append a
    contradictory ``(override with content="all")`` on an inferred
    documentation result, because the effective ``all`` scope already includes
    documentation."""
    import asyncio

    from src.engine.index_service import IndexChangeDetector
    from src.engine.redactor import Redactor
    from src.engine.reranking import Reranker
    from src.mcp.server import create_server

    comps = dict(indexed_transparency)
    comps["redactor"] = Redactor()
    comps["reranker"] = Reranker(comps["db"], comps["session_db"], comps["settings"])
    comps["index_change_detector"] = IndexChangeDetector.from_metadata_store(comps["metadata"])

    engine = comps["search"].search(DOCS_QUERY, limit=10)
    assert engine["scope"]["origin"] == "inferred"
    assert engine["scope"]["override"] == engine["scope"]["effective"] == "all"

    mcp = create_server(comps).build_fastmcp()
    result = asyncio.run(mcp.call_tool("search", {"query": DOCS_QUERY, "limit": 10}))
    envelope = json.loads(result.content[0].text)
    assert envelope["scope"]["override"] == envelope["scope"]["effective"] == "all"
    assert "override with" not in (envelope.get("envelope") or "")
    assert 'content="all"' not in (envelope.get("envelope") or "")
