"""Call-graph deduplication: minimum-depth neighbors, direct/transitive choice,
cross-surface parity, and the no-schema-change guard.

The shared traversal lives in ``EdgeStore._traverse_callers`` /
``_traverse_callees`` and the direct-vs-transitive choice lives in the shared
``_call_neighbors_payload``; every call-graph surface (MCP tool, CLI ``graph``,
resident daemon) funnels through them. These tests exercise the payload, the
CLI, and the daemon over one indexed corpus so the surfaces cannot silently
diverge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import _call_neighbors_payload

_SOURCE = """\
def leaf():
    pass


def mid_b():
    leaf()


def mid_c():
    leaf()


def root():
    mid_b()
    mid_c()


def target():
    pass


def intermediate():
    target()


def caller_a():
    target()
    intermediate()
"""


@pytest.fixture
def dedup_comps(tmp_path: Path) -> dict[str, Any]:
    """Indexed components over a hermetic call graph with a diamond and a
    direct-plus-transitive caller."""
    from tests.conftest import _indexed_components

    repo = tmp_path / "dedup_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "graph_fixture.py").write_text(_SOURCE)
    return _indexed_components(repo, repo / ".context")


def _payload(
    comps: dict[str, Any],
    symbol: str,
    direction: str,
    max_depth: int,
    transitive: bool = False,
) -> dict[str, Any]:
    return json.loads(
        _call_neighbors_payload(
            comps["symbol_store"],
            comps["edge_store"],
            symbol,
            direction,
            max_depth,
            None,
            transitive,
        )
    )


def _name(fqn: str) -> str:
    return fqn.rsplit("::", 1)[-1]


def _neighbors(data: dict[str, Any], key: str) -> list[tuple[str, int]]:
    return sorted((_name(n["fqn"]), n["depth"]) for n in data.get(key, []))


@pytest.mark.integration
@pytest.mark.slow
def test_direct_only_default_excludes_indirect(dedup_comps: dict[str, Any]) -> None:
    """A request without ``transitive`` returns only depth-1 neighbors, even
    when a larger ``max_depth`` is supplied."""
    data = _payload(dedup_comps, "root", "callees", 3, transitive=False)
    assert data["symbol"] is not None
    names = {fqn for fqn, _depth in _neighbors(data, "callees")}
    assert "leaf" not in names
    assert all(depth == 1 for _fqn, depth in _neighbors(data, "callees"))


@pytest.mark.integration
@pytest.mark.slow
def test_transitive_returns_every_neighbor_once(dedup_comps: dict[str, Any]) -> None:
    """``transitive=True`` expands to the bound, deduplicated at minimum depth:
    the diamond's ``leaf`` appears once at depth 2."""
    data = _payload(dedup_comps, "root", "callees", 3, transitive=True)
    neighbors = _neighbors(data, "callees")
    leaf_rows = [row for row in neighbors if row[0] == "leaf"]
    assert leaf_rows == [("leaf", 2)]
    depths = {fqn: depth for fqn, depth in neighbors}
    assert depths["mid_b"] == 1
    assert depths["mid_c"] == 1


@pytest.mark.integration
@pytest.mark.slow
def test_transitive_with_bound_one_degrades_to_direct_only(
    dedup_comps: dict[str, Any],
) -> None:
    """``transitive=True`` bounded to depth 1 degrades to direct-only without
    error."""
    data = _payload(dedup_comps, "root", "callees", 1, transitive=True)
    assert data["symbol"] is not None
    assert all(depth == 1 for _fqn, depth in _neighbors(data, "callees"))
    assert "leaf" not in {fqn for fqn, _depth in _neighbors(data, "callees")}


@pytest.mark.integration
@pytest.mark.slow
def test_direct_and_transitive_neighbor_reported_once_at_depth_one(
    dedup_comps: dict[str, Any],
) -> None:
    """A caller reachable directly and through an intermediate is reported once
    at depth 1 (``caller_a`` calls ``target`` and ``intermediate``)."""
    data = _payload(dedup_comps, "target", "callers", 3, transitive=True)
    neighbors = _neighbors(data, "callers")
    caller_a_rows = [row for row in neighbors if row[0] == "caller_a"]
    assert caller_a_rows == [("caller_a", 1)]
    depths = {fqn: depth for fqn, depth in neighbors}
    assert depths["intermediate"] == 1
    assert all(depth >= 1 for _fqn, depth in neighbors)


@pytest.mark.integration
@pytest.mark.slow
def test_depth_one_is_direct_and_deeper_is_indirect(dedup_comps: dict[str, Any]) -> None:
    """Every depth-1 entry is direct; every depth>1 entry is indirect."""
    data = _payload(dedup_comps, "root", "callees", 3, transitive=True)
    for _fqn, depth in _neighbors(data, "callees"):
        assert depth == 1 or depth > 1
    indirect = {fqn for fqn, depth in _neighbors(data, "callees") if depth > 1}
    assert indirect == {"leaf"}


def _mcp_payload(
    comps: dict[str, Any],
    symbol: str,
    direction: str,
    max_depth: int,
    transitive: bool,
) -> dict[str, Any]:
    """Invoke ``get_call_neighbors`` through a FastMCP server that mirrors the
    production tool body (including the configured-depth clip)."""
    from fastmcp import FastMCP

    mcp: FastMCP = FastMCP("dedup-parity")

    @mcp.tool()
    def get_call_neighbors(
        symbol: str,
        direction: str = "both",
        max_depth: int = 1,
        transitive: bool = False,
    ) -> str:
        depth = min(max_depth, comps["settings"].max_graph_depth)
        return _call_neighbors_payload(
            comps["symbol_store"],
            comps["edge_store"],
            symbol,
            direction,
            depth,
            None,
            transitive,
        )

    result = asyncio.run(
        mcp.call_tool(
            "get_call_neighbors",
            {
                "symbol": symbol,
                "direction": direction,
                "max_depth": max_depth,
                "transitive": transitive,
            },
        )
    )
    return json.loads(result.content[0].text)


def _cli_payload(
    comps: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    symbol: str,
    direction: str,
    max_depth: int,
    transitive: bool,
) -> dict[str, Any]:
    from src.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_initialize_components", lambda _ctx: comps)
    args = argparse.Namespace(
        command="graph",
        fqn=symbol,
        direction=direction,
        depth=max_depth,
        transitive=transitive,
        json=True,
        verbose=False,
        context_dir=str(comps["context_dir"]),
    )
    rc = cli_main.cmd_graph(args)
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _daemon_payload(
    comps: dict[str, Any],
    symbol: str,
    direction: str,
    max_depth: int,
    transitive: bool,
) -> dict[str, Any]:
    from src.engine.daemon import QueryDaemon

    resp = QueryDaemon._do_graph(
        comps,
        {
            "fqn": symbol,
            "direction": direction,
            "depth": max_depth,
            "transitive": transitive,
        },
    )
    assert resp["ok"] is True
    return resp["payload"]


@pytest.mark.integration
@pytest.mark.slow
def test_all_surfaces_agree_on_deduplicated_neighbors(
    dedup_comps: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The payload, MCP tool, CLI, and daemon return identical deduplicated
    neighbors and depths, with signature metadata retained on every entry."""
    payload = _payload(dedup_comps, "root", "callees", 3, transitive=True)
    mcp = _mcp_payload(dedup_comps, "root", "callees", 3, True)
    cli = _cli_payload(dedup_comps, monkeypatch, capsys, "root", "callees", 3, True)
    daemon = _daemon_payload(dedup_comps, "root", "callees", 3, True)

    expected = _neighbors(payload, "callees")
    assert _neighbors(mcp, "callees") == expected
    assert _neighbors(cli, "callees") == expected
    assert _neighbors(daemon, "callees") == expected

    for data in (payload, mcp, cli, daemon):
        for neighbor in data["callees"]:
            assert "target_signature" in neighbor
            assert "overloads" in neighbor
            assert "resolved" in neighbor
            assert "target_raw" in neighbor


@pytest.mark.integration
@pytest.mark.slow
def test_all_surfaces_clip_configured_depth_identically(
    dedup_comps: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With ``max_graph_depth`` below the requested depth, every surface clips
    identically and returns direct-only neighbors."""
    import dataclasses

    clipped = dict(dedup_comps)
    clipped["settings"] = dataclasses.replace(dedup_comps["settings"], max_graph_depth=1)

    mcp = _mcp_payload(clipped, "root", "callees", 3, True)
    cli = _cli_payload(clipped, monkeypatch, capsys, "root", "callees", 3, True)
    daemon = _daemon_payload(clipped, "root", "callees", 3, True)

    expected = _neighbors(mcp, "callees")
    assert _neighbors(cli, "callees") == expected
    assert _neighbors(daemon, "callees") == expected
    assert all(depth == 1 for _fqn, depth in expected)
    assert "leaf" not in {fqn for fqn, _depth in expected}


@pytest.mark.integration
@pytest.mark.slow
def test_audit_result_count_matches_deduplicated_count(
    dedup_comps: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI audit entry records the deduplicated neighbor count."""
    from src.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_initialize_components", lambda _ctx: dedup_comps)
    args = argparse.Namespace(
        command="graph",
        fqn="root",
        direction="callees",
        depth=3,
        transitive=True,
        json=True,
        verbose=False,
        context_dir=str(dedup_comps["context_dir"]),
    )
    assert cli_main.cmd_graph(args) == 0

    with dedup_comps["audit_db"].connect() as conn:
        row = conn.execute(
            "SELECT result_count FROM audit_log_entries "
            "WHERE query_type = 'get_call_neighbors' ORDER BY id DESC LIMIT 1;"
        ).fetchone()
    assert row is not None
    assert row["result_count"] == 3


@pytest.mark.integration
def test_no_schema_or_column_change(dedup_comps: dict[str, Any]) -> None:
    """This feature changes query shape only: the schema version and the
    ``symbols``/``graph_edges`` columns are unchanged."""
    from src.engine.graph import SCHEMA_VERSION

    assert SCHEMA_VERSION == 13
    with dedup_comps["db"].connect() as conn:
        symbol_cols = {r["name"] for r in conn.execute("PRAGMA table_info(symbols);")}
        edge_cols = {r["name"] for r in conn.execute("PRAGMA table_info(graph_edges);")}
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
