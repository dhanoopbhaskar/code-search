"""Local IPC query daemon.

Holds the vector model + SQLite connections warm so repeated CLI invocations
pay socket round-trip latency instead of a per-invocation model load (roughly
0.5-2 s on CPU, depending on the model and disk). Requests and responses are
newline-delimited JSON over a local ``AF_UNIX`` socket under ``.context/`` (or a
short runtime path when that location exceeds the ``AF_UNIX`` limit) — no
network, air-gap preserved. ``AF_UNIX`` is available on Linux, macOS, and
Windows 10 1803+ / Server 2019+, so every supported platform uses the same
transport.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from code_search.engine.embeddings import EmbeddingGenerator, VectorIndex
    from code_search.engine.search import HybridSearch

logger = logging.getLogger(__name__)


def _daemon_freshness(comps: dict[str, Any]) -> dict[str, Any]:
    """Return the shared freshness signal, or a truthful fallback.

    Direct and daemon-forwarded CLI output must agree.
    """
    checker = comps.get("freshness")
    if checker is not None:
        return cast(dict[str, Any], checker.signal())
    metadata = comps.get("metadata")
    status = "unindexed"
    if metadata is not None:
        try:
            status = metadata.get_index_status()
        except Exception:
            status = "unindexed"
    context_dir = comps.get("context_dir")
    index_root = str(Path(context_dir).parent) if context_dir else None
    return {
        "stale": False,
        "stale_change_count": 0,
        "modified_files": 0,
        "deleted_files": 0,
        "new_files": 0,
        "index_age_s": None,
        "index_status": status,
        "index_root": index_root,
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


# ``sockaddr_un.sun_path`` is 104 bytes including the NUL terminator on macOS
# (103 usable) and 108 bytes on Linux and Windows (107 usable); use the
# smallest supported limit so a path chosen on one platform also binds on
# another.
_MAX_UNIX_SOCKET_PATH = 103 if sys.platform == "darwin" else 107

# typeshed omits ``AF_UNIX`` on Windows, so resolve it dynamically to keep the
# module type-checking on every platform. Every supported platform provides it.
_AF_UNIX = cast(int, getattr(socket, "AF_UNIX", None))


def _unix_socket_path_fits(path: Path) -> bool:
    """Return whether *path* fits the ``AF_UNIX`` address limit.

    The limit applies to the encoded path, not to the number of ``str``
    characters, so non-ASCII repository names are measured after filesystem
    encoding.

    Args:
        path: The socket path to measure.

    Returns:
        ``True`` when the encoded path is short enough to bind.
    """

    return len(os.fsencode(path)) <= _MAX_UNIX_SOCKET_PATH


def _user_tag() -> str:
    """Return a stable per-user tag for sockets in a shared temp directory.

    POSIX exposes the numeric uid; Windows has no ``getuid``, so a hashed
    account name keeps the name stable per user without leaking it.
    """

    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        return str(getuid())
    try:
        identity = getpass.getuser()
    except Exception:
        identity = str(Path.home())
    return hashlib.sha256(os.fsencode(identity)).hexdigest()[:8]


def default_socket_path(context_dir: Path) -> Path:
    """Return the IPC socket path the daemon binds for *context_dir*.

    Prefers the conventional ``context_dir / "code-search.sock"``. When that
    path exceeds the ``AF_UNIX`` limit (103 bytes on macOS, 107 elsewhere),
    falls back to a deterministic hashed name under ``$XDG_RUNTIME_DIR`` (when
    set) or the platform temp directory, so a deep checkout path cannot stop
    the daemon from binding.

    Args:
        context_dir: The daemon's context directory (``.context/``).

    Returns:
        The socket path to bind; identical for every process resolving the
        same *context_dir*.
    """

    conventional = context_dir / "code-search.sock"
    if _unix_socket_path_fits(conventional):
        return conventional

    digest = hashlib.sha256(os.fsencode(str(context_dir.expanduser().resolve()))).hexdigest()[:16]
    name = f"code-search-{_user_tag()}-{digest}.sock"
    candidates: list[Path] = []
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        runtime_path = Path(runtime_dir)
        if runtime_path.is_dir() and os.access(runtime_path, os.W_OK):
            candidates.append(runtime_path)
    candidates.append(Path(tempfile.gettempdir()))
    for base in candidates:
        candidate = base / name
        if _unix_socket_path_fits(candidate):
            return candidate
    return Path(tempfile.gettempdir()) / name


def detached_spawn_kwargs() -> dict[str, Any]:
    """Return ``Popen`` options that detach the daemon from the invoking CLI.

    On POSIX a new session lets the daemon outlive the shell. On Windows
    ``start_new_session`` is accepted but ignored, so ``DETACHED_PROCESS`` is
    required to give the child no console of its own; ``CREATE_NEW_PROCESS_GROUP``
    keeps a Ctrl+C in the parent's console from reaching it.

    Returns:
        Keyword arguments to pass to :class:`subprocess.Popen`.
    """

    if os.name == "nt":
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": detached | new_group}
    return {"start_new_session": True}


def _state_path(context_dir: Path) -> Path:
    """Return the daemon lifecycle-state file path for *context_dir*."""
    return context_dir / "code-search.state"


def write_state(context_dir: Path, state: str) -> None:
    """Record the daemon lifecycle state (``starting``/``warming``/``ready``)."""
    with suppress(OSError):
        context_dir.mkdir(parents=True, exist_ok=True)
        _state_path(context_dir).write_text(state)


def read_state(context_dir: Path) -> str | None:
    """Return the recorded daemon lifecycle state, or ``None`` when absent."""
    try:
        return _state_path(context_dir).read_text().strip() or None
    except OSError:
        return None


def clear_state(context_dir: Path) -> None:
    """Remove the lifecycle-state file, ignoring a missing file."""
    with suppress(FileNotFoundError):
        _state_path(context_dir).unlink()


class QueryDaemon:
    """Serves ``search``/``symbol``/``graph``/``ping`` over a local IPC socket.

    Each connection is handled in its own thread. Requests are JSON objects
    with an ``action`` and a ``params`` dict; responses are JSON objects with
    ``ok`` plus the payload, or ``ok: false`` plus an ``error`` string.
    """

    def __init__(
        self,
        socket_path: Path,
        context_dir: Path,
        verbose: bool = False,
    ) -> None:
        """Create a daemon that will serve on *socket_path*.

        Args:
            socket_path: The IPC socket path to bind and serve on.
            context_dir: The daemon's context directory (``.context/``);
                components are initialised lazily in ``start``.
            verbose: When true, enable debug logging on ``stderr``.
        """
        self._socket_path = socket_path
        self._context_dir = context_dir
        self._verbose = verbose
        self._server: socket.socket | None = None
        self._running = threading.Event()
        self._comps: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop_lock = threading.Lock()

    def start(self) -> None:
        """Initialise components, bind the socket, and serve connections forever.

        The IPC socket is bound before the expensive component
        initialisation so a waiting client can observe ``starting``/``warming``
        instead of mistaking a slow start for a crashed daemon. Model warm-up
        runs in the background; ``ping`` reports readiness and the recorded
        lifecycle state. Returns or raises only after ``stop()`` unblocks the
        loop.
        """
        if self._verbose:
            logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        write_state(self._context_dir, "starting")

        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            self._socket_path.unlink()

        server = socket.socket(_AF_UNIX, socket.SOCK_STREAM)
        self._server = server
        server.bind(str(self._socket_path))
        server.listen(8)
        self._running.set()
        logger.info("Query daemon socket bound on %s", self._socket_path)

        init_thread = threading.Thread(
            target=self._initialize, name="code-search-daemon-init", daemon=True
        )
        init_thread.start()

        while self._running.is_set():
            try:
                conn, _addr = server.accept()
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

    def _initialize(self) -> None:
        """Initialise components and warm the model on a background thread."""
        from code_search.cli.main import _initialize_components

        try:
            self._comps = _initialize_components(self._context_dir)
        except Exception as exc:
            logger.exception("Daemon component initialisation failed: %s", exc)
            write_state(self._context_dir, "failed")
            return
        self._ready.set()
        write_state(self._context_dir, "warming")
        try:
            begin_warmup = getattr(self._comps["embedding_gen"], "begin_warmup", None)
            if callable(begin_warmup):
                begin_warmup()
            else:
                self._comps["embedding_gen"].warm_start()
        except Exception as exc:
            logger.warning("Daemon model warm-up failed: %s", exc)
        if self._is_warm(self._comps):
            write_state(self._context_dir, "ready")

    def stop(self) -> None:
        """Stop servicing requests, close the socket, and remove its path.

        Clears the running flag (which ends ``start``'s accept loop), shuts
        down and closes the listening server socket, and unlinks the socket
        file so a stale path cannot block a later ``start``.
        """
        self._running.clear()
        with self._stop_lock:
            server, self._server = self._server, None
            if server is not None:
                with suppress(OSError):
                    server.shutdown(socket.SHUT_RDWR)
                with suppress(OSError):
                    server.close()
        with suppress(OSError):
            self._socket_path.unlink()
        write_state(self._context_dir, "stopped")

    @property
    def is_running(self) -> bool:
        """Return whether the daemon's accept loop is active."""
        return self._running.is_set()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Service one client connection: read, dispatch, and respond.

        Reads a request from *conn*, dispatches it, writes the response, and
        closes the connection. Any exception is logged as a warning so a
        single misbehaving client cannot take down the daemon.

        Args:
            conn: The accepted client socket; always closed on exit.
        """
        try:
            with conn:
                data = self._read_request(conn)
                if not data:
                    return
                response = self._dispatch(data)
                self._send_response(conn, response)
        except Exception as exc:
            logger.warning("Daemon connection error: %s", exc)

    @staticmethod
    def _read_request(conn: socket.socket) -> dict[str, Any] | None:
        """Read and parse one newline-delimited JSON request from *conn*.

        Accumulates bytes until a newline is seen, then parses the line as
        JSON. Returns ``None`` when the connection closes before a full
        request arrives or when the line is not a JSON object.

        Args:
            conn: The client socket to read from.

        Returns:
            The parsed request dict, or ``None`` when no valid request is
            received.
        """
        buffer = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return None
            buffer += chunk
            if b"\n" in buffer:
                line, _rest = buffer.split(b"\n", 1)
                try:
                    parsed = json.loads(line.decode("utf-8"))
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _send_response(conn: socket.socket, payload: dict[str, Any]) -> None:
        """Write *payload* to *conn* as newline-delimited JSON.

        Non-JSON-serialisable values (e.g. paths) fall back to their string
        form via ``default=str``.

        Args:
            conn: The client socket to write to.
            payload: The response dict to serialise and send.
        """
        conn.sendall((json.dumps(payload, default=str) + "\n").encode("utf-8"))

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Route a parsed request to its handler and wrap failures.

        Recognises ``ping``, ``search``, ``symbol``, ``graph``, and
        ``shutdown`` actions. Unknown actions and handler exceptions are
        returned as ``ok: false`` responses rather than being raised, so the
        client always gets a well-formed reply.

        Args:
            request: The parsed request dict; ``action`` selects the handler
                and ``params`` is passed through.

        Returns:
            The response dict for the client.
        """
        action = request.get("action")
        params = request.get("params") or {}
        if action == "shutdown":
            # Stop from a helper thread so the reply still reaches the client;
            # ``stop`` closes the listening socket, which unblocks the accept
            # loop on every platform.
            threading.Thread(target=self.stop, daemon=True).start()
            return {"ok": True, "payload": {"stopping": True}}
        if action == "ping":
            comps = self._comps
            warm = bool(comps is not None and self._is_warm(comps))
            state = read_state(self._context_dir) or ("warming" if comps else "starting")
            if warm:
                state = "ready"
                write_state(self._context_dir, "ready")
            return {"ok": True, "payload": {"pong": True, "warm": warm, "state": state}}
        wait_s = float(params.get("startup_wait_s") or 10.0)
        if self._comps is None and wait_s > 0:
            self._ready.wait(timeout=wait_s)
        comps = self._comps
        if comps is None:
            return {
                "ok": False,
                "error": "daemon is starting",
                "state": read_state(self._context_dir) or "starting",
                "retry_after_ms": 250,
            }
        try:
            if action == "search":
                return self._do_search(comps, params)
            if action == "symbol":
                return self._do_symbol(comps, params)
            if action == "implementations":
                return self._do_implementations(comps, params)
            if action == "graph":
                return self._do_graph(comps, params)
            if action == "find_related":
                return self._do_find_related(comps, params)
            return {"ok": False, "error": f"unknown action: {action!r}"}
        except Exception as exc:
            logger.warning("Daemon action %r failed: %s", action, exc)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _is_warm(comps: dict[str, Any]) -> bool:
        """Return whether the daemon's embedding model is in memory."""
        gen = comps.get("embedding_gen")
        is_warm = getattr(gen, "is_warm", None)
        if callable(is_warm):
            return bool(is_warm())
        return True

    @staticmethod
    def _do_search(comps: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Run a search against the shared components and redact results.

        Searches with the query engine, reranks the hits, and redacts the
        results so forwarded replies match direct CLI output. Every mode
        (ranked, exhaustive, enumerate, rescue tiers) records an append-only
        audit entry so forwarded searches stay as accountable as direct ones.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Search parameters; ``query``, ``limit``, ``language``,
                ``include_tests``, ``mode``, ``content``, ``matching``, and
                ``regex`` are honoured.

        Returns:
            A success payload with ``results`` and ``freshness``, or an error
            response when the context directory has no ready index.
        """
        import time as _time

        from code_search.engine.index_service import IndexChangeDetector
        from code_search.engine.response_service import build_response
        from code_search.engine.search import DEFAULT_CONTENT_SCOPE

        metadata = comps.get("metadata")
        if metadata is not None and metadata.get_index_status() != "ready":
            # Forwarded searches must honour the same precondition as the
            # in-process CLI path; otherwise an unindexed repository returns a
            # successful empty result instead of the actionable error.
            return {"ok": False, "error": "Index not initialized. Run 'code-search index' first."}

        # Block briefly for the model instead of silently serving the reduced
        # lexical path: a cold daemon serves a different (and worse) ranking,
        # so the first forwarded query waits for warmup within a bounded
        # budget. A failed/slow load still proceeds on the reduced path.
        warm_gen = comps.get("embedding_gen")
        wait_warm = getattr(warm_gen, "wait_warm", None)
        if callable(wait_warm):
            settings = comps.get("settings")
            requested = float(params.get("wait_for_warm") or 0.0)
            wait_s = max(float(getattr(settings, "warmup_wait_s", 0.0)), requested)
            if wait_s > 0:
                with suppress(Exception):
                    wait_warm(wait_s)

        start = _time.monotonic()
        envelope = comps["search"].search(
            query=str(params.get("query", "")),
            limit=int(params.get("limit", 10)),
            language=params.get("language"),
            include_tests=bool(params.get("include_tests", False)),
            mode=str(params.get("mode", "ranked")),
            content=params.get("content"),
            matching=params.get("matching"),
            regex=bool(params.get("regex", False)),
            allow_weak=bool(params.get("allow_weak", False)),
        )
        results = envelope["results"]
        reranked = comps["reranker"].rerank(
            results,
            query_terms=params.get("query_terms"),
            query=params.get("query"),
        )
        redacted = comps["redactor"].redact_results(reranked)
        # The forwarded CLI request carries the compact policy; applying it
        # here keeps the daemon (the CLI default path) byte-identical to the
        # in-process path, including relative paths.
        if params.get("compact", True):
            from code_search.engine.response_service import compact_results

            max_lines = params.get("max_snippet_lines")
            redacted = compact_results(
                redacted,
                10 if max_lines is None else int(max_lines),
                paths_only=bool(params.get("paths_only", False)),
            )
        from code_search.engine.response_service import relativize_results

        result_root = comps["metadata"].get("index_root") or str(Path(comps["context_dir"]).parent)
        redacted = relativize_results(redacted, result_root)
        total_redacted = sum(r.get("redacted_count", 0) for r in redacted)
        # Match the CLI's audit semantics: record the engine's per-request
        # timer carried on the envelope, so the served ``query_time_ms`` and
        # the audit row agree after a daemon-forwarded request.
        engine_duration = envelope.get("query_time_ms")
        duration_ms = (
            round(engine_duration)
            if engine_duration is not None
            else int((_time.monotonic() - start) * 1000)
        )
        audit_db = comps.get("audit_db")
        if audit_db is not None:
            try:
                settings = comps["settings"]
                audit_db.write_entry(
                    query_type="search",
                    query_summary=str(params.get("query", ""))[: settings.query_summary_length],
                    result_count=len(redacted),
                    duration_ms=duration_ms,
                    redacted_count=total_redacted,
                )
            except Exception as exc:
                logger.warning("Daemon audit write failed: %s", exc)
        env_mode = str(envelope.get("mode", "ranked"))
        if env_mode in ("exhaustive", "enumerate"):
            count_field = "total_count"
            total = int(envelope.get("total_count", len(redacted)))
        else:
            count_field = "total_matches"
            total = int(envelope["total_matches"])

        # Apply index-change detection and code-scope config hint
        detector = comps.get("index_change_detector")
        if detector is None:
            detector = IndexChangeDetector.from_metadata_store(comps["metadata"])
            comps["index_change_detector"] = detector
        serving = build_response(
            redacted,
            str(params.get("query", "")),
            detector,
            content_scope=envelope.get("content") or DEFAULT_CONTENT_SCOPE,
            metadata_store=comps["metadata"],
            scope_signal=(envelope.get("scope") or {}).get("signal"),
        )

        # If index changed and reload is required, perform in-process reload
        if serving.get("reload_required"):
            logger.info("Index change detected, performing full in-process reload")
            # Reset embedding generator to force model reload
            embedding_gen: EmbeddingGenerator = comps["embedding_gen"]
            embedding_gen.reset_model()
            # Reload vector index from disk
            vector_index: VectorIndex = comps["vector_index"]
            vector_index.load()
            # Reset search engine caches (symbol store, vocabularies, BM25 corpus)
            search_engine: HybridSearch = comps["search"]
            search_engine.reset_caches()
            # Re-initialize the embedding model for the search engine
            search_engine._embedding_generator = embedding_gen
            # Mark reload as complete in detector and update metadata store
            detector.mark_reload_complete(comps["metadata"])
            # Update serving envelope to reflect reload
            serving = build_response(
                redacted,
                str(params.get("query", "")),
                detector,
                content_scope=envelope.get("content") or DEFAULT_CONTENT_SCOPE,
                metadata_store=comps["metadata"],
                scope_signal=(envelope.get("scope") or {}).get("signal"),
            )

        payload: dict[str, Any] = {
            "results": redacted,
            count_field: total,
            "truncated": bool(envelope["truncated"]),
            "vector_health": bool(envelope.get("vector_health")),
            "mode": env_mode,
            "confidence": envelope.get("confidence", "none"),
            "explanation": envelope.get("explanation"),
            "freshness": _daemon_freshness(comps),
        }
        if count_field != "total_matches":
            payload["total_matches"] = total
        if envelope.get("token_savings") is not None:
            payload["token_savings"] = envelope["token_savings"]
        if envelope.get("content") is not None:
            payload["content"] = envelope["content"]
        for count_key in ("production_matches", "test_matches"):
            if envelope.get(count_key) is not None:
                payload[count_key] = envelope[count_key]
        if envelope.get("scope") is not None:
            payload["scope"] = envelope["scope"]
        if envelope.get("matching_semantics") is not None:
            payload["matching_semantics"] = envelope["matching_semantics"]
        if envelope.get("query_time_ms") is not None:
            payload["query_time_ms"] = envelope["query_time_ms"]
        if envelope.get("model_status") is not None:
            payload["model_status"] = envelope["model_status"]
        if envelope.get("ranked_path") is not None:
            payload["ranked_path"] = envelope["ranked_path"]
        if envelope.get("warmup_state") is not None:
            payload["warmup_state"] = envelope["warmup_state"]
        if not QueryDaemon._is_warm(comps):
            payload["warming"] = True
            payload["retry_after_ms"] = 250
        if "degraded_reason" in envelope:
            payload["degraded_reason"] = envelope["degraded_reason"]
        if envelope.get("no_match") is not None:
            payload["no_match"] = envelope["no_match"]
        if "complete" in envelope:
            payload["complete"] = bool(envelope["complete"])
        if envelope.get("excluded"):
            payload["excluded"] = envelope["excluded"]
        if envelope.get("best_effort"):
            payload["best_effort"] = True

        # Add serving-path transparency fields
        if serving.get("envelope") is not None:
            payload["envelope"] = serving["envelope"]
        payload["index_status"] = serving["index_status"]
        payload["index_changed"] = bool(serving.get("index_changed"))
        payload["reload_required"] = bool(serving.get("reload_required"))

        # Surface per-line occurrence metadata in exhaustive responses
        if env_mode == "exhaustive":
            if envelope.get("occurrence_count") is not None:
                payload["occurrence_count"] = envelope["occurrence_count"]
            if envelope.get("literal") is not None:
                payload["literal"] = envelope["literal"]
            if envelope.get("occurrences_per_line") is not None:
                payload["occurrences_per_line"] = envelope["occurrences_per_line"]
            if envelope.get("occurrence_line_numbers") is not None:
                payload["occurrence_line_numbers"] = envelope["occurrence_line_numbers"]

        return {
            "ok": True,
            "payload": payload,
        }

    @staticmethod
    def _do_symbol(comps: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Resolve a symbol by FQN, redacting any returned source code.

        Delegates to the symbol store's ``resolve_name``. Ambiguous and
        not-found outcomes are reported as success payloads with the relevant
        candidates; a found symbol has its ``source_code`` redacted and a
        ``redacted_count`` attached before it is returned.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Request parameters; ``fqn`` selects the symbol.

        Returns:
            A success payload describing the resolution outcome.
        """
        envelope = comps["symbol_store"].resolve_name(str(params.get("fqn", "")))
        kind = envelope["kind"]
        symbol = envelope["symbol"]
        candidates = envelope["candidates"]
        overloads = envelope.get("overloads", [])
        if kind == "ambiguous":
            return {
                "ok": True,
                "payload": {
                    "found": True,
                    "ambiguous": True,
                    "outcome": envelope.get("outcome", "ambiguous"),
                    "symbol": None,
                    "parent": None,
                    "candidates": candidates,
                    "overloads": overloads,
                    "freshness": _daemon_freshness(comps),
                },
            }
        if symbol is None:
            suggestions = [c for c in candidates if c.get("suggestion")]
            return {
                "ok": True,
                "payload": {
                    "found": False,
                    "outcome": envelope.get("outcome", "not_found"),
                    "symbol": None,
                    "candidates": candidates,
                    "overloads": overloads,
                    "ambiguous": False,
                    "suggestion": bool(suggestions),
                    "freshness": _daemon_freshness(comps),
                },
            }
        source_code = symbol.get("source_code") or ""
        redacted_source, redacted_count = comps["redactor"].redact(source_code)
        symbol["source_code"] = redacted_source
        symbol["redacted_count"] = redacted_count
        return {
            "ok": True,
            "payload": {
                "found": True,
                "outcome": envelope.get("outcome", "resolved"),
                "ambiguous": bool(envelope.get("ambiguous")),
                "overloads": overloads,
                "symbol": symbol,
                "candidates": [],
                "freshness": _daemon_freshness(comps),
            },
        }

    @staticmethod
    def _do_implementations(comps: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Resolve an interface member/type to its static implementations.

        Delegates to the shared :func:`find_implementations` rule so daemon
        replies match the MCP tool and CLI command for the same request. The
        optional ``depth`` bounds the reverse traversal; when omitted the
        shared rule's default applies so indirect implementations are returned
        like every other surface.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Request parameters; ``fqn`` selects the reference and the
                optional ``depth`` bounds the traversal.

        Returns:
            A success payload mirroring the dedicated MCP tool with the
            additive ``found`` / ``ambiguous`` fields.
        """
        from code_search.engine.implementations import find_implementations

        settings = comps["settings"]
        depth_param = params.get("depth")
        depth = int(depth_param) if depth_param is not None else settings.max_graph_depth
        result = find_implementations(
            comps["symbol_store"],
            comps["edge_store"],
            str(params.get("fqn", "")),
            max_depth=depth,
        )
        outcome = result.get("outcome")
        payload = dict(result)
        payload["found"] = outcome != "not_found"
        payload["ambiguous"] = outcome == "ambiguous"
        payload["freshness"] = _daemon_freshness(comps)
        payload["query_time_ms"] = 0.0
        audit_db = comps.get("audit_db")
        if audit_db is not None:
            try:
                audit_db.write_entry(
                    query_type="get_implementations",
                    query_summary=str(params.get("fqn", ""))[
                        : comps["settings"].query_summary_length
                    ],
                    result_count=len(payload.get("implementations") or []),
                    duration_ms=0,
                    redacted_count=0,
                )
            except Exception as exc:
                logger.warning("Daemon audit write failed: %s", exc)
        return {"ok": True, "payload": payload}

    @staticmethod
    def _do_graph(comps: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Return callers/callees for a symbol, mirroring the MCP contract.

        Reuses the MCP server's neighbor-payload builder so daemon and MCP
        replies agree. The requested depth is capped at the configured
        ``max_graph_depth``.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Request parameters; ``fqn``, ``direction``, ``depth``, and
                ``transitive`` are honoured.

        Returns:
            A success payload with the symbol plus ``callers`` and ``callees``,
            or the ambiguous/not-found outcome.
        """
        from code_search.mcp.server import _call_neighbors_payload

        settings = comps["settings"]
        direction = params.get("direction", "both")
        if direction == "implements":
            from code_search.engine.implementations import find_implementations

            result = find_implementations(
                comps["symbol_store"],
                comps["edge_store"],
                str(params.get("fqn", "")),
            )
            outcome = result.get("outcome")
            payload = dict(result)
            payload["found"] = outcome != "not_found"
            payload["ambiguous"] = outcome == "ambiguous"
            payload["callers"] = []
            payload["callees"] = []
            payload["freshness"] = _daemon_freshness(comps)
            return {"ok": True, "payload": payload}
        depth = min(int(params.get("depth", 1)), settings.max_graph_depth)
        data = json.loads(
            _call_neighbors_payload(
                comps["symbol_store"],
                comps["edge_store"],
                str(params.get("fqn", "")),
                direction,
                depth,
                comps.get("freshness"),
                bool(params.get("transitive", False)),
                comps.get("db"),
            )
        )
        if data.get("symbol") is None and data.get("candidates"):
            return {
                "ok": True,
                "payload": {
                    "found": False,
                    "ambiguous": True,
                    "outcome": data.get("outcome", "ambiguous"),
                    "symbol": None,
                    "candidates": data["candidates"],
                    "callers": [],
                    "callees": [],
                    "freshness": data.get("freshness", _daemon_freshness(comps)),
                },
            }
        if data.get("symbol") is None:
            return {
                "ok": True,
                "payload": {
                    "found": False,
                    "outcome": data.get("outcome", "not_found"),
                    "symbol": None,
                    "callers": [],
                    "callees": [],
                    "freshness": data.get("freshness", _daemon_freshness(comps)),
                },
            }
        return {
            "ok": True,
            "payload": {
                "found": True,
                "outcome": data.get("outcome", "resolved"),
                "symbol": data["symbol"],
                "callers": data["callers"],
                "callees": data["callees"],
                "freshness": data.get("freshness", _daemon_freshness(comps)),
            },
        }

    @staticmethod
    def _do_find_related(comps: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Find semantically related chunks for a given file and line.

        Delegates anchor resolution and neighbour ranking to the shared
        :func:`code_search.engine.find_related.find_related` rule so daemon
        replies agree with the MCP tool; the daemon adds only the freshness
        signal carried by every forwarded reply.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Request parameters; ``file_path``, ``line_number``, and
                ``limit`` are honoured.

        Returns:
            A success envelope whose ``payload`` is the shared find-related
            payload plus ``freshness``.
        """
        from code_search.engine.config import Settings
        from code_search.engine.find_related import find_related

        settings = comps.get("settings") or Settings.from_env()
        payload = find_related(
            comps,
            str(params.get("file_path", "")),
            int(params.get("line_number", 0)),
            int(params.get("limit", settings.find_related_limit)),
        )
        payload["freshness"] = _daemon_freshness(comps)
        return {"ok": True, "payload": payload}


class DaemonClient:
    """Synchronous IPC client used by CLI forwarding and ``daemon status``."""

    def __init__(self, socket_path: Path, timeout: float = 30.0) -> None:
        """Create a client for the daemon listening on *socket_path*.

        Args:
            socket_path: The IPC socket path of the running daemon.
            timeout: Connect/read timeout in seconds for each request.
        """
        self._socket_path = socket_path
        self._timeout = timeout

    @staticmethod
    def is_running(socket_path: Path) -> bool:
        """Return whether a daemon socket file currently exists at *socket_path*.

        Args:
            socket_path: The IPC socket path to probe.

        Returns:
            ``True`` when the socket file exists; note this is a liveness
            heuristic — a stale file may briefly report ``True``.
        """
        return socket_path.exists()

    @staticmethod
    def is_serving(socket_path: Path, timeout: float = 0.1) -> bool:
        """Return whether a daemon actually answers ``ping`` on *socket_path*.

        Unlike :meth:`is_running`, this distinguishes a live listener from a
        stale socket file left behind by a crashed daemon.

        Args:
            socket_path: The IPC socket path to probe.
            timeout: Connect/read timeout in seconds.

        Returns:
            ``True`` when the socket answers a ``ping`` request.
        """
        if not socket_path.exists():
            return False
        try:
            response = DaemonClient(socket_path, timeout=timeout).request("ping")
        except Exception:
            return False
        return bool(response.get("ok"))

    def request(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one request to the daemon and return its parsed response.

        Opens a fresh connection, writes ``{action, params}`` as newline-
        delimited JSON, and reads until a newline-delimited JSON object is
        received.

        Args:
            action: The daemon action to invoke (e.g. ``ping``, ``search``).
            params: Optional parameters passed alongside the action.

        Returns:
            The daemon's response dict.

        Raises:
            RuntimeError: When the daemon closes the connection without
                sending a response.
        """
        payload = {"action": action, "params": params or {}}
        with socket.socket(_AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._timeout)
            sock.connect(str(self._socket_path))
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buffer = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                if b"\n" in buffer:
                    line, _rest = buffer.split(b"\n", 1)
                    parsed = json.loads(line.decode("utf-8"))
                    if isinstance(parsed, dict):
                        return parsed
        raise RuntimeError("daemon closed connection without a response")


def daemon_status(context_dir: Path) -> dict[str, Any]:
    """Return ``{running, warm, socket, pid}`` for *context_dir*'s daemon.

    ``running`` is reported only when the socket exists and answers ``ping``
    within the timeout; ``warm`` mirrors the daemon's model readiness.
    """
    sock = default_socket_path(context_dir)
    if not sock.exists():
        return {"running": False, "warm": False, "socket": str(sock), "pid": None}
    try:
        client = DaemonClient(sock, timeout=1.0)
        resp = client.request("ping")
        payload = resp.get("payload") or {}
        return {
            "running": True,
            "warm": bool(payload.get("warm")),
            "state": payload.get("state") or read_state(context_dir),
            "socket": str(sock),
            "pid": _read_pidfile(context_dir),
        }
    except Exception:
        return {
            "running": False,
            "warm": False,
            "state": read_state(context_dir),
            "socket": str(sock),
            "pid": _read_pidfile(context_dir),
        }


def _pidfile_path(context_dir: Path) -> Path:
    """Return the convention pidfile path for *context_dir*.

    Args:
        context_dir: The daemon's context directory (``.context/``).

    Returns:
        ``context_dir / "code-search.pid"``.
    """

    return context_dir / "code-search.pid"


def write_pidfile(context_dir: Path) -> None:
    """Record the current process id in *context_dir*'s pidfile.

    Creates the directory if needed and writes the current PID, so ``daemon
    status`` can report the owning process.

    Args:
        context_dir: The daemon's context directory (``.context/``).
    """
    context_dir.mkdir(parents=True, exist_ok=True)
    _pidfile_path(context_dir).write_text(str(os.getpid()))


def _read_pidfile(context_dir: Path) -> int | None:
    """Read and parse the pidfile id, or ``None`` when absent/invalid."""
    try:
        return int(_pidfile_path(context_dir).read_text().strip())
    except Exception:
        return None


def process_exists(pid: int) -> bool:
    """Return whether *pid* names a live process without signalling it.

    ``os.kill(pid, 0)`` is a harmless existence probe on POSIX, but on Windows
    every signal other than the two console events unconditionally terminates
    the target, so the existence check must go through ``OpenProcess`` there.

    Args:
        pid: The process id to probe.

    Returns:
        ``True`` when the process exists (including when it belongs to another
        user), ``False`` when it does not.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
        get_last_error = ctypes.get_last_error  # type: ignore[attr-defined]
        kernel32 = win_dll("kernel32", use_last_error=True)
        access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        still_active = 259
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED means the process exists but is not ours.
            return int(get_last_error()) == 5
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return bool(exit_code.value == still_active)
            return True
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_is_alive(context_dir: Path) -> bool:
    """Return whether the pidfile records a live process.

    Used before removing a socket that does not answer yet: a daemon that has
    bound its socket but is still initialising must not be mistaken for a
    crashed one.

    Args:
        context_dir: The daemon's context directory (``.context/``).

    Returns:
        ``True`` when a pid is recorded and the process exists.
    """
    pid = _read_pidfile(context_dir)
    if pid is None:
        return False
    return process_exists(pid)


def clear_pidfile(context_dir: Path) -> None:
    """Remove *context_dir*'s pidfile, ignoring a missing file.

    Args:
        context_dir: The daemon's context directory (``.context/``).
    """
    with suppress(FileNotFoundError):
        _pidfile_path(context_dir).unlink()


def run_daemon_foreground(context_dir: Path, socket_path: Path, verbose: bool) -> int:
    """Run the daemon in the foreground (blocking); used by ``daemon start``.

    Returns 0 on clean shutdown.
    """
    daemon = QueryDaemon(socket_path, context_dir, verbose=verbose)
    write_pidfile(context_dir)
    try:
        daemon.start()
    finally:
        daemon.stop()
        clear_pidfile(context_dir)
        clear_state(context_dir)
    return 0
