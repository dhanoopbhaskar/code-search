"""Local unix-socket query daemon.

Holds the vector model + SQLite connections warm so repeated CLI invocations
pay socket round-trip latency instead of a per-invocation model load (roughly
0.5-2 s on CPU, depending on the model and disk). Requests and responses are
newline-delimited JSON over a unix socket under ``.context/`` — no network,
air-gap preserved.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from src.engine.config import Settings
from src.engine.embeddings import EmbeddingGenerator, VectorIndex
from src.engine.index_service import IndexChangeDetector
from src.engine.redactor import Redactor
from src.engine.response_service import build_response
from src.engine.search import DEFAULT_CONTENT_SCOPE, HybridSearch

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


def default_socket_path(context_dir: Path) -> Path:
    """Return the unix-socket path the daemon binds for *context_dir*.

    Args:
        context_dir: The daemon's context directory (``.context/``).

    Returns:
        The convention ``context_dir / "code-search.sock"`` path.
    """

    return context_dir / "code-search.sock"


class QueryDaemon:
    """Serves ``search``/``symbol``/``graph``/``ping`` over a unix socket.

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
            socket_path: The unix-socket path to bind and serve on.
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

    def start(self) -> None:
        """Initialise components, bind the socket, and serve connections forever.

        Initialises components via ``_initialize_components``, binds the unix
        socket (removing any stale socket file first), starts the embedding
        model warming in the background, and blocks in an accept loop — each
        connection is serviced on its own daemon thread. Binding first means
        ``ping`` and ``search`` are answerable while the model is still warming;
        a forwarded query during warmup is served from the reduced cold path.
        Returns or raises only after ``stop()`` unblocks the loop.
        """
        from src.cli.main import _initialize_components

        if self._verbose:
            logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        self._comps = _initialize_components(self._context_dir)

        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(FileNotFoundError):
            self._socket_path.unlink()

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self._socket_path))
        self._server.listen(8)
        self._running.set()
        logger.info("Query daemon listening on %s", self._socket_path)

        # Warm the model in the background after binding so readiness probes and
        # searches are answered while the load is in flight.
        try:
            begin_warmup = getattr(self._comps["embedding_gen"], "begin_warmup", None)
            if callable(begin_warmup):
                begin_warmup()
            else:
                self._comps["embedding_gen"].warm_start()
        except Exception as exc:
            logger.warning("Daemon model warm-up failed: %s", exc)

        while self._running.is_set():
            try:
                conn, _addr = self._server.accept()
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

    def stop(self) -> None:
        """Stop servicing requests, close the socket, and remove its path.

        Clears the running flag (which ends ``start``'s accept loop), shuts
        down and closes the listening server socket, and unlinks the socket
        file so a stale path cannot block a later ``start``.
        """
        self._running.clear()
        if self._server is not None:
            with suppress(OSError):
                self._server.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                self._server.close()
        with suppress(FileNotFoundError):
            self._socket_path.unlink()

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

        Recognises ``ping``, ``search``, ``symbol``, and ``graph`` actions.
        Unknown actions and handler exceptions are returned as ``ok: false``
        responses rather than being raised, so the client always gets a
        well-formed reply.

        Args:
            request: The parsed request dict; ``action`` selects the handler
                and ``params`` is passed through.

        Returns:
            The response dict for the client.
        """
        action = request.get("action")
        params = request.get("params") or {}
        comps = self._comps
        if comps is None:
            return {"ok": False, "error": "daemon components not initialised"}
        try:
            if action == "ping":
                return {"ok": True, "payload": {"pong": True, "warm": self._is_warm(comps)}}
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
                ``include_tests``, and ``mode`` are honoured.

        Returns:
            A success payload with ``results`` and ``freshness``.
        """
        import time as _time

        start = _time.monotonic()
        envelope = comps["search"].search(
            query=str(params.get("query", "")),
            limit=int(params.get("limit", 10)),
            language=params.get("language"),
            include_tests=bool(params.get("include_tests", True)),
            mode=str(params.get("mode", "ranked")),
            content=params.get("content"),
            matching=params.get("matching"),
        )
        results = envelope["results"]
        reranked = comps["reranker"].rerank(
            results,
            query_terms=params.get("query_terms"),
            query=params.get("query"),
        )
        redacted = comps["redactor"].redact_results(reranked)
        total_redacted = sum(r.get("redacted_count", 0) for r in redacted)
        duration_ms = int((_time.monotonic() - start) * 1000)
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
        if envelope.get("content") is not None:
            payload["content"] = envelope["content"]
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
        from src.engine.implementations import find_implementations

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
        from src.mcp.server import _call_neighbors_payload

        settings = comps["settings"]
        direction = params.get("direction", "both")
        if direction == "implements":
            from src.engine.implementations import find_implementations

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

        Mirrors the MCP server's find_related logic so daemon and MCP
        replies agree on boilerplate exclusion and file_role biasing.

        Args:
            comps: The shared component registry (see ``_initialize_components``).
            params: Request parameters; ``file_path``, ``line_number``, and ``limit``
                are honoured.

        Returns:
            A success payload with ``results``, ``vector_health``, ``status``,
            ``query_time_ms``, and ``freshness`` — or an ``error`` payload when no
            indexed chunk is found.
        """
        import time as _time
        from pathlib import Path

        from src.engine.classification import FileRole, file_role
        from src.engine.paths import normalize_indexed_path, resolve_stored_path

        start = _time.monotonic()
        embedding_gen: EmbeddingGenerator = comps["embedding_gen"]
        vector_index: VectorIndex = comps["vector_index"]
        settings = comps.get("settings") or Settings.from_env()
        redactor = comps.get("redactor") or Redactor()

        index_root = Path(comps["context_dir"]).parent
        stored_root = comps["metadata"].get("index_root")
        if stored_root:
            index_root = Path(stored_root)

        file_path = str(params.get("file_path", ""))
        line_number = int(params.get("line_number", 0))
        limit = int(params.get("limit", settings.find_related_limit))

        stored_path: str | None = None
        normalized = normalize_indexed_path(file_path, index_root)
        if normalized is not None:
            with comps["db"].connect() as conn:
                stored_path = resolve_stored_path(normalized, conn)

        if stored_path is None:
            return {
                "ok": True,
                "payload": {
                    "error": f"No indexed chunk found at '{file_path}:{line_number}'",
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }

        with comps["db"].connect() as conn:
            row = conn.execute(
                "SELECT id, fqn, content, language FROM code_chunks "
                "WHERE file_path = ? AND line_start <= ? AND line_end >= ? "
                "LIMIT 1;",
                (stored_path, line_number, line_number),
            ).fetchone()
            if row is None:
                return {
                    "ok": True,
                    "payload": {
                        "error": f"No indexed chunk found at '{file_path}:{line_number}'",
                        "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                        "freshness": _daemon_freshness(comps),
                    },
                }
            anchor_id = row["id"]
            chunk_content = row["content"] or ""

        query_vec = embedding_gen.encode(chunk_content)
        if query_vec is None:
            return {
                "ok": True,
                "payload": {
                    "results": [],
                    "vector_health": False,
                    "status": "empty",
                    "explanation": (
                        "vector layer unavailable; find_related requires the embedding model"
                    ),
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }

        limit = min(limit, settings.find_related_limit)
        if vector_index.size <= 1:
            explanation = (
                "no related chunks found; the index holds only the anchor chunk"
                if vector_index.size == 1
                else "no related chunks found; the vector index is empty"
            )
            return {
                "ok": True,
                "payload": {
                    "results": [],
                    "vector_health": vector_index.size == 1,
                    "status": "empty",
                    "explanation": explanation,
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }

        # Directional boilerplate suppression — a non-boilerplate
        # anchor excludes boilerplate-shape neighbors (MODEL/DTO/ASSEMBLER/
        # EXCEPTION) by default; a genuine DTO/model anchor still finds its
        # scaffolding peers when the anchor is itself boilerplate.
        boilerplate_roles = {
            FileRole.MODEL,
            FileRole.DTO,
            FileRole.ASSEMBLER,
            FileRole.EXCEPTION,
        }
        analysis_paths = set(settings.analysis_artifact_paths)
        anchor_role = file_role(stored_path, analysis_paths=analysis_paths)
        anchor_is_boilerplate = anchor_role in boilerplate_roles
        boilerplate_on = bool(settings.find_related_exclude_boilerplate)
        exclude_boilerplate = boilerplate_on and not anchor_is_boilerplate
        downweight_boilerplate = (not boilerplate_on) and not anchor_is_boilerplate

        exclude_file = bool(settings.find_related_exclude_file)
        # Fetch limit + 1 candidates before filtering (the limit-1 fix): an anchor
        # that is its own cosine top-1 must still yield a full limit of neighbours.
        search_results = vector_index.search(
            query_vec,
            top_k=limit + 1,
            exclude_file_paths={stored_path} if exclude_file else None,
        )

        def _build_results(
            scored: list[tuple[int, float]], same_file_flag: bool
        ) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
            """Return ``(kept_results, boilerplate_only, raw_results)``.

            Applies the directional boilerplate exclusion/down-weight; ``kept`` is
            the neighbour set after the filter, ``raw`` is the unfiltered set
            (used for the ``best_effort`` label), and ``boilerplate_only``
            reports whether the only similar content was boilerplate-shape.
            """
            chunk_ids = [cid for cid, _ in scored if cid != anchor_id]
            if not chunk_ids:
                return [], False, []
            score_map = {cid: sc for cid, sc in scored}
            placeholders = ",".join("?" for _ in chunk_ids)
            with comps["db"].connect() as conn:
                chunk_rows = conn.execute(
                    f"SELECT id, fqn, file_path, line_start, line_end, content, "
                    f"language FROM code_chunks "
                    f"WHERE id IN ({placeholders});",
                    chunk_ids,
                ).fetchall()

            rows: list[dict[str, Any]] = []
            had_boilerplate = False
            for cr in chunk_rows:
                role = file_role(cr["file_path"], analysis_paths=analysis_paths)
                if role in boilerplate_roles:
                    had_boilerplate = True
                content = cr["content"] or ""
                redacted_content, _redacted_count = redactor.redact(content)
                rows.append(
                    {
                        "chunk_id": cr["id"],
                        "file_path": cr["file_path"],
                        "line_start": cr["line_start"],
                        "line_end": cr["line_end"],
                        "content": redacted_content,
                        "fqn": cr["fqn"],
                        "language": cr["language"],
                        "similarity": score_map.get(cr["id"], 0.0),
                        "same_file": same_file_flag,
                        "file_role": role,
                    }
                )
            if downweight_boilerplate:
                penalty = settings.find_related_same_file_penalty
                for r in rows:
                    if r["file_role"] in boilerplate_roles:
                        r["similarity"] = r["similarity"] * penalty
                rows.sort(key=lambda r: r["similarity"], reverse=True)
            if exclude_boilerplate:
                kept = [r for r in rows if r["file_role"] not in boilerplate_roles]
                boilerplate_only = (not kept) and had_boilerplate
                return kept[:limit], boilerplate_only, rows[:limit]
            all_boilerplate = bool(rows) and all(r["file_role"] in boilerplate_roles for r in rows)
            return rows[:limit], all_boilerplate, rows[:limit]

        def _best_effort(rows: list[dict[str, Any]], same_file: bool) -> dict[str, Any]:
            return {
                "ok": True,
                "payload": {
                    "results": rows,
                    "vector_health": True,
                    "status": "best_effort",
                    "explanation": (
                        "only boilerplate-shape content is similar to this anchor; "
                        "returning the best-effort match"
                    ),
                    "same_file": same_file,
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }

        if exclude_file:
            cross_results, cross_boilerplate_only, cross_raw = _build_results(
                search_results, same_file_flag=False
            )
            if cross_results:
                return {
                    "ok": True,
                    "payload": {
                        "results": cross_results,
                        "vector_health": True,
                        "status": "cross_file",
                        "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                        "freshness": _daemon_freshness(comps),
                    },
                }
            if cross_boilerplate_only:
                return _best_effort(cross_raw, same_file=False)
            # Exclusion left no cross-file neighbour: search the full index again
            # (anchor file included) for the best-effort same-file result.
            fallback = vector_index.search(query_vec, top_k=limit + 1)
            same_file_results, same_boilerplate_only, _same_file_raw = _build_results(
                fallback, same_file_flag=True
            )
            if same_file_results:
                if same_boilerplate_only:
                    return _best_effort(same_file_results, same_file=True)
                return {
                    "ok": True,
                    "payload": {
                        "results": same_file_results,
                        "vector_health": True,
                        "status": "same_file_only",
                        "explanation": (
                            "no cross-file neighbours; returning the best same-file result"
                        ),
                        "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                        "freshness": _daemon_freshness(comps),
                    },
                }
            return {
                "ok": True,
                "payload": {
                    "results": [],
                    "vector_health": True,
                    "status": "empty",
                    "explanation": (
                        "no related chunks found; the anchor file holds the only similar content"
                    ),
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }

        # Down-weighting mode (CODE_SEARCH_FIND_RELATED_EXCLUDE_FILE=false): the
        # anchor file is kept, but same-file chunks are down-weighted so cross-file
        # neighbours always outrank them. Cross-file candidates are
        # ranked first by score, then same-file candidates by their penalized score.
        penalty = settings.find_related_same_file_penalty
        chunk_ids = [cid for cid, _ in search_results]
        placeholders = ",".join("?" for _ in chunk_ids)
        with comps["db"].connect() as conn:
            file_rows = conn.execute(
                f"SELECT id, file_path FROM code_chunks WHERE id IN ({placeholders});",
                chunk_ids,
            ).fetchall()
        file_by_id = {r["id"]: r["file_path"] for r in file_rows}
        anchor_file = stored_path
        cross_scored: list[tuple[int, float]] = []
        same_scored: list[tuple[int, float]] = []
        for cid, score in search_results:
            if cid == anchor_id:
                continue
            if file_by_id.get(cid, "") == anchor_file:
                same_scored.append((cid, score * penalty))
            else:
                cross_scored.append((cid, score))
        cross_scored.sort(key=lambda item: item[1], reverse=True)
        same_scored.sort(key=lambda item: item[1], reverse=True)
        scored = (cross_scored + same_scored)[:limit]

        cross_results, cross_boilerplate_only, _cross_raw = _build_results(
            cross_scored[:limit], same_file_flag=False
        )
        if cross_results:
            return {
                "ok": True,
                "payload": {
                    "results": cross_results,
                    "vector_health": True,
                    "status": "cross_file",
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }
        same_file_results, same_boilerplate_only, _same_file_raw = _build_results(
            scored, same_file_flag=True
        )
        if same_file_results:
            if same_boilerplate_only or cross_boilerplate_only:
                return _best_effort(same_file_results, same_file=True)
            return {
                "ok": True,
                "payload": {
                    "results": same_file_results,
                    "vector_health": True,
                    "status": "same_file_only",
                    "explanation": "no cross-file neighbours; returning the best same-file result",
                    "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                    "freshness": _daemon_freshness(comps),
                },
            }
        return {
            "ok": True,
            "payload": {
                "results": [],
                "vector_health": True,
                "status": "empty",
                "explanation": "no related chunks found",
                "query_time_ms": round((_time.monotonic() - start) * 1000, 1),
                "freshness": _daemon_freshness(comps),
            },
        }


class DaemonClient:
    """Synchronous unix-socket client used by CLI forwarding and ``daemon status``."""

    def __init__(self, socket_path: Path, timeout: float = 30.0) -> None:
        """Create a client for the daemon listening on *socket_path*.

        Args:
            socket_path: The unix-socket path of the running daemon.
            timeout: Connect/read timeout in seconds for each request.
        """
        self._socket_path = socket_path
        self._timeout = timeout

    @staticmethod
    def is_running(socket_path: Path) -> bool:
        """Return whether a daemon socket file currently exists at *socket_path*.

        Args:
            socket_path: The unix-socket path to probe.

        Returns:
            ``True`` when the socket file exists; note this is a liveness
            heuristic — a stale file may briefly report ``True``.
        """
        return socket_path.exists()

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
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
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
            "socket": str(sock),
            "pid": _read_pidfile(context_dir),
        }
    except Exception:
        return {"running": False, "warm": False, "socket": str(sock), "pid": None}


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
    return 0
