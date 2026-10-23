"""Unit tests for daemon readiness and bind-first startup.

The daemon binds the socket before warming, so ``ping`` answers ``warm: false``
while the model loads; ``daemon start`` is idempotent (at most one daemon per
context directory); and a dead socket/pidfile reports ``running: false`` without
hanging.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from code_search.engine.daemon import DaemonClient, QueryDaemon, daemon_status, default_socket_path


class _FakeGenerator:
    """Minimal stand-in exposing the warmup surface the daemon relies on."""

    def __init__(self) -> None:
        self.warm = False

    def is_warm(self) -> bool:
        return self.warm

    def begin_warmup(self) -> None:
        return None


def _start_daemon_with_fake(
    monkeypatch: object, tmp_path: Path
) -> tuple[QueryDaemon, threading.Thread, dict]:
    fake = _FakeGenerator()
    comps: dict[str, Any] = {"embedding_gen": fake}

    def _components_for(_ctx: Any, **_kwargs: Any) -> dict[str, Any]:
        return comps

    monkeypatch.setattr("code_search.cli.main._initialize_components", _components_for)

    socket_path = default_socket_path(tmp_path)
    daemon = QueryDaemon(socket_path, tmp_path)
    thread = threading.Thread(target=daemon.start, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert socket_path.exists(), "daemon failed to bind its socket"
    return daemon, thread, comps


def test_ping_reports_warm_false_then_true(monkeypatch, tmp_path: Path) -> None:
    daemon, thread, comps = _start_daemon_with_fake(monkeypatch, tmp_path)
    try:
        client = DaemonClient(default_socket_path(tmp_path), timeout=2.0)
        first = client.request("ping")
        assert first["payload"]["pong"] is True
        assert first["payload"]["warm"] is False

        comps["embedding_gen"].warm = True
        second = client.request("ping")
        assert second["payload"]["warm"] is True
    finally:
        daemon.stop()
        thread.join(timeout=5)


def test_daemon_start_is_idempotent_when_socket_exists(tmp_path: Path) -> None:
    import argparse

    from code_search.cli.main import cmd_daemon

    socket_path = default_socket_path(tmp_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")

    args = argparse.Namespace(
        daemon_action="start",
        port=str(socket_path),
        verbose=False,
        context_dir=str(tmp_path),
    )
    assert cmd_daemon(args) == 0


def test_dead_socket_reports_not_running_without_hanging(tmp_path: Path) -> None:
    socket_path = default_socket_path(tmp_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")  # stale socket file, no listener
    start = time.monotonic()
    status = daemon_status(tmp_path)
    assert status["running"] is False
    assert status["warm"] is False
    assert time.monotonic() - start < 2.0


def test_missing_socket_reports_not_running(tmp_path: Path) -> None:
    status = daemon_status(tmp_path)
    assert status == {
        "running": False,
        "warm": False,
        "socket": str(default_socket_path(tmp_path)),
        "pid": None,
    }


def test_is_serving_true_for_live_listener(monkeypatch, tmp_path: Path) -> None:
    """A bound daemon that answers ``ping`` is reported as serving."""
    daemon, thread, _comps = _start_daemon_with_fake(monkeypatch, tmp_path)
    try:
        assert DaemonClient.is_serving(default_socket_path(tmp_path), timeout=2.0) is True
    finally:
        daemon.stop()
        thread.join(timeout=5)


def test_is_serving_false_for_stale_socket(tmp_path: Path) -> None:
    """A socket file with no listener is not reported as serving."""
    socket_path = default_socket_path(tmp_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")

    assert DaemonClient.is_serving(socket_path, timeout=0.1) is False


def test_ensure_resident_service_keeps_starting_daemon(monkeypatch, tmp_path: Path) -> None:
    """A live pid plus a socket that starts answering is not unlinked."""
    import argparse

    from code_search.cli import main as cli_main
    from code_search.engine.daemon import write_pidfile

    socket_path = default_socket_path(tmp_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")  # bound but not ready yet
    write_pidfile(tmp_path)  # records this (live) process

    probes = {"count": 0}

    def fake_is_serving(_path: Path, timeout: float = 0.1) -> bool:
        probes["count"] += 1
        return probes["count"] > 1

    monkeypatch.setattr(
        "code_search.engine.daemon.DaemonClient.is_serving",
        staticmethod(fake_is_serving),
    )
    spawned: list[object] = []
    monkeypatch.setattr("subprocess.Popen", lambda *args, **_: spawned.append(args))

    args = argparse.Namespace(context_dir=str(tmp_path))

    assert cli_main._ensure_resident_service(args) is True
    assert socket_path.exists(), "a starting daemon must not be unlinked"
    assert spawned == []


def test_ensure_resident_service_removes_stale_socket(tmp_path: Path) -> None:
    """A socket without a live pid is removed so the next call can start cleanly."""
    import argparse

    from code_search.cli import main as cli_main

    socket_path = default_socket_path(tmp_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text("")

    args = argparse.Namespace(context_dir=str(tmp_path))

    assert cli_main._ensure_resident_service(args) is False
    assert not socket_path.exists()


def test_ensure_resident_service_requires_a_live_daemon(monkeypatch: Any, tmp_path: Path) -> None:
    """A spawn that never binds must not claim the model load.

    The caller relies on this ``False`` to start its own warmup; returning
    ``True`` for a dead daemon leaves every query on the lexical path.
    """
    import argparse

    from code_search.cli import main as cli_main

    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: object())

    args = argparse.Namespace(context_dir=str(tmp_path))

    assert cli_main._ensure_resident_service(args) is False


def test_long_context_path_uses_a_short_socket(tmp_path: Path) -> None:
    """A deep checkout must still produce a bindable ``AF_UNIX`` path."""
    context_dir = tmp_path / ("x" * 100) / ".context"
    context_dir.mkdir(parents=True)

    socket_path = default_socket_path(context_dir)

    assert socket_path != context_dir / "code-search.sock"
    assert len(os.fsencode(str(socket_path))) <= 107
    assert socket_path == default_socket_path(context_dir), "path must be deterministic"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(str(socket_path))


def test_daemon_forwarded_search_surfaces_scope_signal_and_override(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    """A daemon-served search reports the effective scope and a
    usable CLI-dialect override on the human output path, exactly as the direct
    path does."""
    import argparse

    from code_search.cli import main as cli_main

    payload = {
        "results": [],
        "total_matches": 0,
        "query_time_ms": 12.0,
        "freshness": {},
        "envelope": "configuration excluded; use content scope config",
        "scope": {
            "effective": "code",
            "origin": "explicit",
            "intent": "config",
            "suggested": None,
            "signal": "configuration excluded; use content scope config",
            "override": "config",
        },
    }
    monkeypatch.setattr(cli_main, "_resolve_context_dir", lambda _args: tmp_path)
    monkeypatch.setattr(DaemonClient, "is_running", staticmethod(lambda _sock: True))
    monkeypatch.setattr(
        DaemonClient,
        "request",
        lambda _self, _action, _params=None: {"ok": True, "payload": payload},
    )

    args = argparse.Namespace(
        command="search",
        query="database configuration",
        limit=10,
        language=None,
        include_tests=True,
        mode="ranked",
        content="code",
        matching=None,
        json=False,
        no_model=True,
        verbose=False,
        context_dir=str(tmp_path),
    )
    assert cli_main._try_forward_to_daemon(args) == 0
    err = capsys.readouterr().err
    assert "configuration excluded" in err
    assert "Override with: --content config" in err


def test_daemon_forwarded_search_reports_match_split(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    """The daemon-forwarded human path reports the same production/test split
    as the local path instead of hiding the counts."""
    import argparse

    from code_search.cli import main as cli_main

    payload = {
        "results": [],
        "total_matches": 11,
        "production_matches": 8,
        "test_matches": 3,
        "query_time_ms": 12.0,
        "freshness": {},
    }
    monkeypatch.setattr(cli_main, "_resolve_context_dir", lambda _args: tmp_path)
    monkeypatch.setattr(DaemonClient, "is_running", staticmethod(lambda _sock: True))
    monkeypatch.setattr(
        DaemonClient,
        "request",
        lambda _self, _action, _params=None: {"ok": True, "payload": payload},
    )

    args = argparse.Namespace(
        command="search",
        query="login",
        limit=10,
        language=None,
        include_tests=False,
        mode="ranked",
        content=None,
        matching=None,
        json=False,
        no_model=True,
        verbose=False,
        context_dir=str(tmp_path),
    )
    assert cli_main._try_forward_to_daemon(args) == 0
    out = capsys.readouterr().out
    assert "Matches: 8 production + 3 test (hidden; use --include-tests)" in out
