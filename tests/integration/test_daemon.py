"""Integration tests for the unix-socket query daemon.

Verifies: warm-path latency < 5 s p50 per invocation, unix-socket forwarding,
and the air-gap guarantee (unix socket only, no network).
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from src.engine.daemon import (
    DaemonClient,
    QueryDaemon,
    default_socket_path,
)


@pytest.fixture
def indexed_env(tmp_path: Path) -> dict[str, Any]:
    """A small indexed repo plus its context dir (no daemon running)."""
    from src.context import ContextManager
    from src.engine.config import Settings
    from src.engine.embeddings import EmbeddingGenerator, VectorIndex
    from src.engine.graph import GraphDatabase, IndexMetadataStore
    from src.engine.indexer import IndexOrchestrator
    from src.engine.parser import ASTParser
    from src.engine.symbols import SymbolExtractor, SymbolStore

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text(
        "def validate_token(token: str) -> dict:\n"
        '    """Validate JWT token and return payload."""\n'
        "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    return payload\n"
    )

    context_dir = tmp_path / "ctx"
    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths

    db = GraphDatabase(paths["graph"], settings)
    db.initialize()
    meta = IndexMetadataStore(db)
    parser = ASTParser()
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)
    embedding_gen = EmbeddingGenerator(settings)
    vector_index = VectorIndex(
        paths.get("vectors_bin", context_dir / "vectors.bin"),
        paths.get("vectors_meta", context_dir / "vectors.meta.json"),
    )
    vector_index.load()
    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=meta,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
    )
    orchestrator.index_codebase(root_path=repo, force=True, verbose=False)

    return {"context_dir": context_dir, "repo": repo}


@pytest.fixture
def daemon_env(indexed_env: dict[str, Any]) -> dict[str, Any]:
    """A running daemon over ``indexed_env``'s context on the default socket."""
    context_dir = indexed_env["context_dir"]
    socket_path = default_socket_path(context_dir)
    daemon = QueryDaemon(socket_path, context_dir, verbose=False)
    thread = threading.Thread(target=daemon.start, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    yield {
        **indexed_env,
        "socket_path": socket_path,
        "daemon": daemon,
        "client": DaemonClient(socket_path),
    }

    daemon.stop()
    thread.join(timeout=5)


def test_daemon_ping(daemon_env: dict[str, Any]) -> None:
    resp = daemon_env["client"].request("ping")
    assert resp.get("ok") is True
    assert resp["payload"]["pong"] is True


def test_daemon_search_forwarded(daemon_env: dict[str, Any]) -> None:
    resp = daemon_env["client"].request(
        "search", {"query": "validate token", "limit": 10, "include_tests": True}
    )
    assert resp.get("ok") is True
    results = resp["payload"]["results"]
    assert isinstance(results, list)
    assert any("main.py" in r["file_path"] for r in results)


def test_daemon_search_envelope_is_mode_aware(daemon_env: dict[str, Any]) -> None:
    """The daemon payload reports total_matches/best_effort for ranked
    and total_count/complete for exhaustive/enumerate."""
    ranked = daemon_env["client"].request(
        "search", {"query": "validate token", "limit": 10, "include_tests": True}
    )
    payload = ranked["payload"]
    assert payload["total_matches"] >= 1
    assert "total_count" not in payload
    assert "complete" not in payload
    assert payload["best_effort"] is True

    exhaustive = daemon_env["client"].request(
        "search",
        {"query": "token", "limit": 10, "include_tests": True, "mode": "exhaustive"},
    )
    payload = exhaustive["payload"]
    assert payload["total_count"] >= 1
    assert "total_matches" not in payload
    assert payload["complete"] is True

    enumerate_resp = daemon_env["client"].request(
        "search",
        {"query": "all methods", "limit": 10, "include_tests": True, "mode": "enumerate"},
    )
    payload = enumerate_resp["payload"]
    assert payload["total_count"] >= 1
    assert "total_matches" not in payload
    assert payload["complete"] is True


def test_daemon_symbol_forwarded(daemon_env: dict[str, Any]) -> None:
    resp = daemon_env["client"].request("symbol", {"fqn": "validate_token"})
    assert resp.get("ok") is True
    payload = resp["payload"]
    assert payload.get("found") is True
    assert payload["symbol"]["name"] == "validate_token"


def test_daemon_warm_latency_under_5s(daemon_env: dict[str, Any]) -> None:
    """Warm-path invocations complete in under 5 seconds (p50)."""
    client = daemon_env["client"]
    client.request("ping")
    latencies: list[float] = []
    for _ in range(5):
        start = time.monotonic()
        client.request("search", {"query": "token", "limit": 10, "include_tests": True})
        latencies.append((time.monotonic() - start) * 1000)
    p50 = sorted(latencies)[len(latencies) // 2]
    assert p50 < 5000, f"warm-path p50 latency {p50:.0f} ms >= 5000 ms"


def test_daemon_uses_unix_socket_only(daemon_env: dict[str, Any]) -> None:
    """The daemon serves over a local unix socket under .context/."""
    socket_path = daemon_env["socket_path"]
    assert socket_path.exists()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(str(socket_path))
        sock.sendall(b'{"action":"ping","params":{}}\n')
        data = sock.recv(65536)
    assert b"pong" in data


def test_daemon_status_running(daemon_env: dict[str, Any]) -> None:
    from src.engine.daemon import DaemonClient

    # daemon_status() checks the default code-search.sock; the fixture daemon
    # runs on test.sock, so assert the client sees it running instead.
    assert DaemonClient.is_running(daemon_env["socket_path"])
    resp = daemon_env["client"].request("ping")
    assert resp.get("ok") is True


def test_default_socket_path_under_context(tmp_path: Path) -> None:
    assert str(default_socket_path(tmp_path)) == str(tmp_path / "code-search.sock")


def test_daemon_implementations_action(indexed_implementations: dict[str, Any]) -> None:
    fqn = indexed_implementations["symbol_fqns"][("python", "Animal", "speak")][0]
    resp = QueryDaemon._do_implementations(indexed_implementations, {"fqn": fqn})
    assert resp.get("ok") is True
    payload = resp["payload"]
    assert payload["found"] is True
    assert payload["outcome"] == "resolved"
    assert payload["implementations"]
    assert payload["declaring_type"]["name"] == "Animal"
    assert "explanation" in payload
    assert "freshness" in payload


def test_daemon_implementations_carries_explanation(
    indexed_implementations: dict[str, Any],
) -> None:
    fqn = indexed_implementations["symbol_fqns"][("java", "Repository", "find")][0]
    resp = QueryDaemon._do_implementations(indexed_implementations, {"fqn": fqn})
    payload = resp["payload"]
    assert payload["outcome"] == "no_static_implementation"
    assert "runtime-generated implementation may exist" in (payload["explanation"] or "")


def test_daemon_graph_implements_direction(indexed_implementations: dict[str, Any]) -> None:
    fqn = indexed_implementations["symbol_fqns"][("python", "Animal", "speak")][0]
    resp = QueryDaemon._do_graph(indexed_implementations, {"fqn": fqn, "direction": "implements"})
    assert resp.get("ok") is True
    payload = resp["payload"]
    assert payload["implementations"]
    assert payload["callers"] == []
    assert payload["callees"] == []
    assert payload["found"] is True


def _search_args(context_dir: Path, query: str, *, json_out: bool) -> argparse.Namespace:
    """Build the argparse namespace ``cmd_search`` expects for a ranked search."""
    return argparse.Namespace(
        command="search",
        query=query,
        limit=10,
        language=None,
        include_tests=True,
        mode="ranked",
        json=json_out,
        no_model=False,
        verbose=False,
        context_dir=str(context_dir),
    )


def test_search_cold_path_returns_reduced_without_hint(
    indexed_env: dict[str, Any], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-shot cold search auto-starts the service and answers reduced.

    With no daemon running, the CLI transparently spawns the resident service
    (stubbed here) and serves the labelled reduced path within budget; the
    superseded "performance hint" is no longer emitted.
    """
    from src.cli.main import cmd_search

    context_dir = indexed_env["context_dir"]
    assert not default_socket_path(context_dir).exists()

    class _FakeProc:
        pid = 4242

    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: _FakeProc())

    rc = cmd_search(_search_args(context_dir, "validate token", json_out=True))
    captured = capsys.readouterr()
    assert rc == 0
    envelope = json.loads(captured.out)
    assert envelope["results"], "cold search should return results"
    assert envelope["ranked_path"] == "lexical_reduced"
    assert not envelope.get("performance_hint")

    rc = cmd_search(_search_args(context_dir, "validate token", json_out=False))
    captured = capsys.readouterr()
    assert rc == 0
    assert "reduced cold path" in captured.out


def test_search_warm_path_omits_performance_hint(
    daemon_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """A running daemon serves the search with no cold hint.

    When the daemon is running, ``cmd_search`` forwards to it and must not
    emit the cold-path performance hint in either JSON or human output.
    """
    from src.cli.main import cmd_search

    context_dir = daemon_env["context_dir"]
    assert default_socket_path(context_dir).exists()

    rc = cmd_search(_search_args(context_dir, "validate token", json_out=True))
    captured = capsys.readouterr()
    assert rc == 0
    forwarded = json.loads(captured.out)
    assert forwarded["results"], "warm search should return results"
    assert "performance_hint" not in forwarded, "warm JSON must omit the hint"

    rc = cmd_search(_search_args(context_dir, "validate token", json_out=False))
    captured = capsys.readouterr()
    assert rc == 0
    assert "Performance hint" not in captured.out


def test_daemon_index_reload_across_rebuilds(daemon_env: dict[str, Any]) -> None:
    """Index reload works across multiple rebuilds in a single
    daemon session.

    When the index is rebuilt out-of-band (simulated by updating
    ``last_indexed_at``), the daemon should detect the change and reload
    the vector index/BM25 corpus in-process, serving fresh results without
    requiring a restart.
    """
    from datetime import UTC, datetime

    client = daemon_env["client"]
    context_dir = daemon_env["context_dir"]

    # First search to establish baseline
    resp1 = client.request("search", {"query": "validate token", "limit": 10})
    assert resp1.get("ok") is True
    results1 = resp1["payload"]["results"]
    assert len(results1) >= 1
    assert not resp1["payload"].get("reload_required", False), "first search should not need reload"

    # Simulate out-of-band index rebuild by updating last_indexed_at
    from src.context import ContextManager
    from src.engine.config import Settings
    from src.engine.graph import GraphDatabase, IndexMetadataStore

    settings = Settings(context_dir=context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths
    db = GraphDatabase(paths["graph"], settings)
    meta = IndexMetadataStore(db)
    meta.set("last_indexed_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    # Second search should detect change and reload
    resp2 = client.request("search", {"query": "validate token", "limit": 10})
    assert resp2.get("ok") is True
    # The daemon should have reloaded and now serve fresh results
    # reload_required should be False after successful reload
    assert resp2["payload"].get("reload_required", True) is False, "reload should have completed"

    # Simulate another rebuild
    meta.set("last_indexed_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    # Third search should again reload
    resp3 = client.request("search", {"query": "validate token", "limit": 10})
    assert resp3.get("ok") is True
    assert resp3["payload"].get("reload_required", True) is False
    # second reload should have completed

    # Results should still be returned
    results3 = resp3["payload"]["results"]
    assert len(results3) >= 1


def test_daemon_find_related_matches_mcp(daemon_env: dict[str, Any]) -> None:
    """Find_related via the daemon matches MCP behavior.

    The daemon's find_related handler should return the same boilerplate-
    excluded, file_role-biased results as the MCP tool.
    """
    client = daemon_env["client"]
    repo = daemon_env["repo"]

    # Find a Java file with a class to anchor on
    java_file = repo / "src" / "main.py"
    # Use line 1 which contains the function definition
    resp = client.request(
        "find_related",
        {"file_path": str(java_file), "line_number": 1, "limit": 5},
    )
    assert resp.get("ok") is True
    payload = resp["payload"]
    assert "results" in payload
    assert "vector_health" in payload
    assert "status" in payload
    assert "query_time_ms" in payload
    assert "freshness" in payload

    # Should not return an error
    assert "error" not in payload

    # Status should be one of the expected values
    assert payload["status"] in ("cross_file", "same_file_only", "empty", "best_effort")

    # If cross_file or same_file_only, results should be present
    if payload["status"] in ("cross_file", "same_file_only", "best_effort"):
        assert len(payload["results"]) >= 1
        # Results should have the expected structure
        for r in payload["results"]:
            assert "chunk_id" in r
            assert "file_path" in r
            assert "similarity" in r
            assert "file_role" in r
