"""Integration tests for transparent resident-service auto-start.

A one-shot query with no daemon running auto-starts the resident service and
returns a labelled reduced response promptly; once the service is warm a
subsequent forwarded query is ``hybrid``; and a dead socket does not hang the
next query.
"""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FIXTURES_DIR, _indexed_components


@pytest.fixture
def autostart_env(tmp_path: Path) -> dict[str, Any]:
    """An indexed repo with no daemon running."""
    repo = tmp_path / "r"
    shutil.copytree(FIXTURES_DIR / "relevance", repo)
    context_dir = tmp_path / "ctx"
    comps = _indexed_components(repo, context_dir, settings_kwargs={"index_prose": True})
    return {**comps, "repo": repo}


def _search_args(context_dir: Path, query: str, *, json_out: bool) -> argparse.Namespace:
    return argparse.Namespace(
        command="search",
        query=query,
        limit=5,
        language=None,
        include_tests=True,
        mode="ranked",
        content=None,
        matching=None,
        json=json_out,
        no_model=False,
        verbose=False,
        context_dir=str(context_dir),
    )


def test_one_shot_autostarts_then_forwards_warm(
    autostart_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from src.cli.main import cmd_search
    from src.engine.daemon import DaemonClient, QueryDaemon, daemon_status, default_socket_path

    context_dir = autostart_env["context_dir"]
    socket_path = default_socket_path(context_dir)
    assert not socket_path.exists()

    started: dict[str, Any] = {}

    class _FakeProc:
        pid = 4242

    def fake_popen(cmd: list[str], **_kwargs: Any) -> _FakeProc:
        port = Path(cmd[cmd.index("--port") + 1])
        daemon = QueryDaemon(port, context_dir)
        thread = threading.Thread(target=daemon.start, daemon=True)
        started["daemon"] = daemon
        started["thread"] = thread
        thread.start()
        return _FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    try:
        rc = cmd_search(_search_args(context_dir, "how do comments get created", json_out=True))
        captured = capsys.readouterr()
        assert rc == 0
        first = json.loads(captured.out)
        assert first["ranked_path"] in ("lexical_reduced", "hybrid")
        assert first["results"], "the reduced path returns real lexical results"

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not daemon_status(context_dir).get("warm"):
            time.sleep(0.1)
        assert daemon_status(context_dir)["running"] is True

        rc = cmd_search(_search_args(context_dir, "how do comments get created", json_out=True))
        captured = capsys.readouterr()
        assert rc == 0
        second = json.loads(captured.out)
        assert second["ranked_path"] == "hybrid"
        assert second["model_status"]["state"] == "warm"
        assert second["degraded_reason"] is None
        assert DaemonClient.is_running(socket_path)
    finally:
        daemon = started.get("daemon")
        if daemon is not None:
            daemon.stop()
        thread = started.get("thread")
        if thread is not None:
            thread.join(timeout=5)


def test_dead_socket_does_not_hang_next_query(
    autostart_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    from src.cli.main import cmd_search
    from src.engine.daemon import default_socket_path

    context_dir = autostart_env["context_dir"]
    socket_path = default_socket_path(context_dir)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")  # stale socket with no listener

    start = time.monotonic()
    rc = cmd_search(_search_args(context_dir, "how do comments get created", json_out=True))
    captured = capsys.readouterr()
    elapsed = time.monotonic() - start
    assert rc == 0
    envelope = json.loads(captured.out)
    assert envelope["ranked_path"] in ("lexical_reduced", "hybrid")
    assert elapsed < 5.0, f"a dead socket hung the query for {elapsed:.1f}s"
