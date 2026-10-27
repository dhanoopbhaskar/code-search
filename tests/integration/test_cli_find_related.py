"""CLI ``find-related`` parity with the MCP tool."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def indexed_tsreact(tmp_path: Path) -> dict[str, Any]:
    """Index a copy of the TS/React fixture."""
    repo = tmp_path / "tsreact_repo"
    shutil.copytree(FIXTURES_DIR / "tsreact", repo)
    return _indexed_components(repo, repo / ".context", settings_kwargs={"index_prose": True})


@pytest.fixture
def long_anchor_repo(tmp_path: Path) -> dict[str, Any]:
    """Index a repo with two functions so line 0 and line 42 resolve differently."""
    repo = tmp_path / "anchor_repo"
    (repo / "src").mkdir(parents=True)
    prepare = "def prepare_orders(orders):\n    return orders\n\n\n"
    body = "\n".join(f"    step_{index} = {index}" for index in range(1, 41))
    (repo / "src" / "orders.py").write_text(
        f"{prepare}def process_orders(orders):\n{body}\n    return orders\n"
    )
    (repo / "src" / "fulfilment.py").write_text(
        "def fulfil_orders(orders):\n    return [order for order in orders]\n"
    )
    return _indexed_components(repo, repo / ".context")


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from code_search.cli.main import main

    previous = sys.argv
    sys.argv = ["code-search", *argv]
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    finally:
        sys.argv = previous
    return code, capsys.readouterr().out


def test_cli_find_related_json_is_relative_and_shared(
    indexed_tsreact: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI command returns the shared payload with relative paths."""
    repo: Path = indexed_tsreact["repo"]
    context_dir: Path = indexed_tsreact["context_dir"]
    anchor = repo / "src" / "store" / "articlesSlice.ts"

    code, out = _run_cli(
        [
            "find-related",
            str(anchor),
            "--line",
            "4",
            "--json",
            f"--context-dir={context_dir}",
        ],
        capsys,
    )

    assert code == 0
    payload = json.loads(out)
    assert "results" in payload
    for result in payload["results"]:
        assert not Path(result["file_path"]).is_absolute()


def test_shared_resolver_anchors_the_requested_line(long_anchor_repo: dict[str, Any]) -> None:
    """The shared resolver selects the chunk containing line 42, not line 0."""
    from code_search.engine.find_related import resolve_anchor_chunk

    repo: Path = long_anchor_repo["repo"]
    anchor_file = repo / "src" / "orders.py"

    anchor = resolve_anchor_chunk(long_anchor_repo["db"], str(anchor_file), 42, repo)
    assert anchor is not None
    assert anchor.line_start <= 42 <= anchor.line_end
    wrong_anchor = resolve_anchor_chunk(long_anchor_repo["db"], str(anchor_file), 0, repo)
    assert wrong_anchor is None or not (wrong_anchor.line_start <= 42 <= wrong_anchor.line_end)


def _normalized_result(result: dict[str, Any], repo: Path) -> tuple[Any, ...]:
    """Return the transport-independent identity of a neighbour result."""
    path = Path(result["file_path"])
    if path.is_absolute():
        path = path.relative_to(repo)
    fqn = result.get("fqn") or ""
    prefix = f"{repo.resolve().as_posix()}/"
    if fqn.startswith(prefix):
        fqn = fqn[len(prefix) :]
    return (
        path.as_posix(),
        result["line_start"],
        result["line_end"],
        fqn,
        round(float(result.get("similarity", 0.0)), 6),
    )


def test_cli_find_related_through_daemon_matches_mcp(
    long_anchor_repo: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The daemon receives ``line_number`` and returns the same neighbours as MCP."""
    from code_search.cli.main import cmd_find_related
    from code_search.engine.daemon import DaemonClient, QueryDaemon, default_socket_path
    from code_search.mcp.server import _find_related_payload

    repo: Path = long_anchor_repo["repo"]
    context_dir: Path = long_anchor_repo["context_dir"]
    anchor_file = repo / "src" / "orders.py"
    socket_path = default_socket_path(context_dir)

    daemon = QueryDaemon(socket_path, context_dir)
    thread = threading.Thread(target=daemon.start, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not DaemonClient.is_serving(socket_path):
            time.sleep(0.02)
        assert DaemonClient.is_serving(socket_path), "daemon did not start"

        args = argparse.Namespace(
            command="find-related",
            file_path=str(anchor_file),
            line=42,
            limit=5,
            json=True,
            compact=True,
            pretty=False,
            context_dir=str(context_dir),
            no_startup_check=True,
            verbose=False,
        )
        assert cmd_find_related(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "error" not in payload, payload
        assert payload["results"]

        mcp_payload = json.loads(_find_related_payload(long_anchor_repo, str(anchor_file), 42, 5))
        assert [_normalized_result(r, repo) for r in payload["results"]] == [
            _normalized_result(r, repo) for r in mcp_payload["results"]
        ]
    finally:
        daemon.stop()
        thread.join(timeout=5)
