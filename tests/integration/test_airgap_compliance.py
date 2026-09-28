from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest


def test_airgap_patches_socket() -> None:
    from src.engine.redactor import air_gap_enforcement

    with air_gap_enforcement():
        import socket

        with pytest.raises(RuntimeError, match="Air-gap violation"):
            s = socket.socket()
            s.connect(("127.0.0.1", 1))

    import socket

    s = socket.socket()
    assert s is not None
    s.close()


def test_airgap_verify_function() -> None:
    from src.engine.redactor import verify_air_gap

    result = verify_air_gap()
    assert result is True


def test_airgap_no_outbound_on_import() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, '.'); "
            "from src.engine.redactor import verify_air_gap; "
            "assert verify_air_gap(), 'Air-gap check failed'",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_redact_then_search_integration() -> None:
    from src.engine.redactor import Redactor

    redactor = Redactor()

    test_content = (
        "def authenticate():\n"
        '    api_key = "sk-1234567890abcdef"\n'
        '    password = "hunter2"\n'
        "    return True\n"
    )

    results = [
        {
            "chunk_id": 1,
            "file_path": "src/auth.py",
            "line_start": 1,
            "line_end": 5,
            "content": test_content,
            "fqn": "src.auth.authenticate",
            "language": "python",
            "score": 0.95,
            "is_definition": True,
            "is_test_file": False,
            "redacted_count": 0,
        }
    ]

    redacted = redactor.redact_results(results)
    assert len(redacted) == 1
    r = redacted[0]
    assert r["redacted_count"] >= 2
    assert "[REDACTED]" in r["content"]
    assert "sk-1234567890abcdef" not in r["content"]
    assert "hunter2" not in r["content"]
    assert "authenticate" in r["content"]
    assert "api_key" in r["content"] or "[REDACTED]" in r["content"]


def test_audit_redact_roundtrip(tmp_path: Path) -> None:
    from src.engine.audit import AuditDatabase
    from src.engine.redactor import Redactor

    audit_db = AuditDatabase(tmp_path / "audit.db")
    audit_db.initialize()

    redactor = Redactor()

    test_text = 'api_key = "sk_abcdefghijklmnop"'
    redacted, redacted_count = redactor.redact(test_text)

    audit_db.write_entry(
        query_type="search",
        query_summary="test API key search",
        result_count=1,
        duration_ms=50,
        redacted_count=redacted_count,
    )

    entries = audit_db.get_entries()
    assert len(entries) == 1
    assert entries[0]["redacted_count"] == redacted_count
    assert entries[0]["query_type"] == "search"
    assert "[REDACTED]" in redacted


def test_cli_main_wraps_with_air_gap(tmp_path: Path) -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "list-languages",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"
    assert "Supported languages" in result.stdout


def test_cli_airgap_blocks_network(tmp_path: Path) -> None:
    import subprocess
    import sys

    script = tmp_path / "test_airgap.py"
    script.write_text(
        textwrap.dedent("""\
            import sys
            sys.path.insert(0, '.')
            from src.engine.redactor import air_gap_enforcement

            with air_gap_enforcement():
                import socket
                try:
                    s = socket.socket()
                    s.connect(('127.0.0.1', 1))
                    print('UNEXPECTED: connect succeeded')
                except RuntimeError:
                    print('Air-gap violation')
        """),
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Air-gap violation" in result.stdout


def test_mcp_server_imports_air_gap() -> None:
    import inspect

    from src.cli import main as cli_main

    source = inspect.getsource(cli_main.cmd_serve)
    assert "air_gap_enforcement" in source


def test_match_boost_query_makes_no_outbound_call(indexed_match_boost: dict[str, Any]) -> None:
    """A ranked query exercising the match-boost layer makes no outbound call."""
    from src.engine.redactor import air_gap_enforcement

    with air_gap_enforcement():
        envelope = indexed_match_boost["search"].search("README", limit=5, content="docs")
    assert envelope["results"]
    assert envelope["results"][0]["score_sources"]["match_boost"]["tier"] == "exact_filename"


def test_daemon_autostart_is_local_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The transparent auto-start spawns the local daemon over a unix socket.

    The one-shot invocation must not make an outbound network connection: the
    spawned process is the local ``daemon run`` command bound to a socket under
    the context directory, and the readiness probe uses that unix socket.
    """
    import argparse

    from src.cli.main import _ensure_resident_service
    from src.engine.daemon import default_socket_path
    from src.engine.redactor import air_gap_enforcement

    captured: dict[str, Any] = {}

    class _FakeProc:
        pid = 4242

    def fake_popen(cmd: list[str], **_kwargs: Any) -> _FakeProc:
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    args = argparse.Namespace(context_dir=str(tmp_path), command="search", no_model=False)

    with air_gap_enforcement():
        owns_warmup = _ensure_resident_service(args)

    assert owns_warmup is True
    command = captured["cmd"]
    assert "daemon" in command and "run" in command
    socket_arg = command[command.index("--port") + 1]
    expected_socket = default_socket_path(Path(args.context_dir).resolve())
    assert socket_arg == str(expected_socket)


def test_match_boost_module_imports_are_local() -> None:
    """``match_boost.py`` imports no network or third-party dependency."""
    import ast

    source = (Path(__file__).resolve().parents[2] / "src" / "engine" / "match_boost.py").read_text()
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    forbidden = {
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "telnetlib",
        "numpy",
        "model2vec",
        "rank_bm25",
        "fastmcp",
    }
    assert not (modules & forbidden), f"forbidden imports: {modules & forbidden}"
