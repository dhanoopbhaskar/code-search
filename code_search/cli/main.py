"""CLI entry point for the code-search engine.

Provides subcommands:
  index, search, symbol, graph, implementations, query, path, explain,
  affected, map, metrics, serve, list-languages, download-models, daemon
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from code_search.engine.config import Settings

if TYPE_CHECKING:
    from code_search.engine.audit import AuditDatabase

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    """Configure root logging to stderr.

    Args:
        verbose: When true, set the level to ``DEBUG``; otherwise ``WARNING``.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _initialize_components(
    context_dir: Path,
    settings: Settings | None = None,
    load_vectors: bool = True,
    for_index: bool = False,
) -> dict[str, Any]:
    """Create and wire up all engine components for a given context directory.

    Args:
        context_dir: Directory holding the index, vectors, and session/audit DBs.
        settings: Optional pre-resolved settings (for CLI flag overrides); when
            omitted the environment and ``context_dir`` determine the config.
        load_vectors: Whether to load the on-disk vector index. Commands that
            only use the symbol graph skip the sidecar load, which is the
            largest fixed cost of a one-shot invocation.
        for_index: Resolve the layout from *settings* (the requested write
            layout) instead of the layout recorded in index metadata.
    """
    from code_search.context import ContextManager
    from code_search.engine.audit import AuditDatabase
    from code_search.engine.embeddings import (
        EmbeddingGenerator,
        VectorIndex,
    )
    from code_search.engine.embeddings import (
        _reset_warned_keys as _reset_embedding_warnings,
    )
    from code_search.engine.graph import EdgeStore, GraphDatabase, IndexMetadataStore
    from code_search.engine.indexer import IndexOrchestrator
    from code_search.engine.metrics import MetricsCollector
    from code_search.engine.parser import ASTParser
    from code_search.engine.parser import _reset_warned_keys as _reset_parser_warnings
    from code_search.engine.redactor import Redactor
    from code_search.engine.reranking import Reranker
    from code_search.engine.search import HybridSearch
    from code_search.engine.session import SessionDatabase
    from code_search.engine.symbols import SymbolExtractor, SymbolStore

    _reset_parser_warnings()
    _reset_embedding_warnings()
    settings = settings or Settings.with_context_dir(context_dir)
    ctx = ContextManager(settings)
    ctx.ensure()
    paths = ctx.paths
    db = GraphDatabase(paths["graph"], settings)
    db.initialize()

    metadata_store = IndexMetadataStore(db)
    edge_store = EdgeStore(db)
    parser = ASTParser(settings=settings)
    symbol_extractor = SymbolExtractor(parser)
    symbol_store = SymbolStore(db, settings)

    embedding_gen = EmbeddingGenerator(settings)
    recorded_layout = (
        settings.index_layout
        if for_index
        else (metadata_store.get("index_layout") or settings.index_layout)
    )
    compact_layout = recorded_layout == "compact"
    vectors_bin = context_dir / ("vectors.v2.bin" if compact_layout else "vectors.bin")
    vectors_meta = context_dir / ("vectors.v2.meta" if compact_layout else "vectors.meta.json")
    vector_index = VectorIndex(
        vectors_bin,
        vectors_meta,
        compact=compact_layout,
    )
    if compact_layout:
        path_cache: dict[int, str | None] = {}

        def _chunk_path(chunk_id: int) -> str | None:
            if chunk_id in path_cache:
                return path_cache[chunk_id]
            try:
                with db.connect() as conn:
                    row = conn.execute(
                        "SELECT file_path FROM code_chunks WHERE id = ?;", (chunk_id,)
                    ).fetchone()
                resolved = str(row["file_path"]) if row is not None else None
            except Exception:
                resolved = None
            path_cache[chunk_id] = resolved
            return resolved

        vector_index.set_path_lookup(_chunk_path)
    if load_vectors:
        vector_index.load()

    try:
        session_db = SessionDatabase(paths["session"], settings)
        session_db.initialize()
    except Exception:
        logger.warning("Session DB unavailable; running without session weighting")
        session_db = None

    audit_db = AuditDatabase(paths["audit"])
    audit_db.initialize()

    from code_search.engine.freshness import FreshnessChecker

    freshness = FreshnessChecker(
        db=db,
        metadata=metadata_store,
        parser=parser,
        context_dir=context_dir,
        settings=settings,
    )

    orchestrator = IndexOrchestrator(
        db=db,
        metadata_store=metadata_store,
        parser=parser,
        symbol_extractor=symbol_extractor,
        symbol_store=symbol_store,
        embedding_generator=embedding_gen,
        vector_index=vector_index,
        context_dir=context_dir,
        settings=settings,
        edge_store=edge_store,
        freshness=freshness,
    )

    hybrid_search = HybridSearch(db, vector_index, embedding_gen, settings)
    reranker = Reranker(db, session_db, settings)
    redactor = Redactor()

    metrics_collector = MetricsCollector(settings)

    from code_search.engine.index_service import IndexChangeDetector

    index_change_detector = IndexChangeDetector.from_metadata_store(metadata_store)

    return {
        "db": db,
        "metadata": metadata_store,
        "edge_store": edge_store,
        "parser": parser,
        "symbol_store": symbol_store,
        "embedding_gen": embedding_gen,
        "vector_index": vector_index,
        "session_db": session_db,
        "audit_db": audit_db,
        "orchestrator": orchestrator,
        "search": hybrid_search,
        "reranker": reranker,
        "redactor": redactor,
        "metrics_collector": metrics_collector,
        "freshness": freshness,
        "settings": settings,
        "context_dir": context_dir,
        "index_change_detector": index_change_detector,
    }


def _check_model_profile(settings: Settings) -> int | None:
    """Validate the selected model profile; return an exit code when unusable.

    The ``fast`` profile is opt-in and local-only. It is withheld (reported
    unavailable) unless its model is present locally, so a quality- or
    latency-collapsing option is never silently substituted.

    Args:
        settings: Active settings carrying ``model_profile``.

    Returns:
        ``None`` when the profile can be used, else a non-zero exit code.
    """
    if settings.model_profile == "default":
        return None
    from code_search.engine.embeddings import profile_model_available

    try:
        settings.resolve_embedding_profile()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not profile_model_available(settings):
        print(
            f"Error: model profile '{settings.model_profile}' is not available. The "
            "fast profile is withheld unless a local model meets the measured "
            "latency/quality floors; place the model under models/ or set "
            "CODE_SEARCH_FAST_EMBEDDING_MODEL, then re-run the tradeoff evaluation.",
            file=sys.stderr,
        )
        return 1
    return None


def _make_index_progress_reporter() -> Callable[[str, int, int], None]:
    """Build a callback that prints indexing progress at 10% milestones.

    The returned callback accepts ``(phase, completed, total)`` and writes a
    line to stderr the first time completion in each phase reaches a new
    multiple of ten percent, keeping output sparse for long indexes.

    Returns:
        A stateful progress callback suitable for
        ``IndexOrchestrator.index_codebase``.
    """
    milestones: dict[str, int] = {}

    def report(phase: str, completed: int, total: int) -> None:
        if total <= 0:
            return
        pct = min(100, (completed * 100) // total)
        milestone = (pct // 10) * 10
        if milestone < 10 or milestone <= milestones.get(phase, -1):
            return
        milestones[phase] = milestone
        print(f"Indexing {phase}: {milestone}% ({completed}/{total})", file=sys.stderr)

    return report


def _make_index_status_reporter() -> Callable[[str], None]:
    """Build a callback that prints a one-line status message for a slow step.

    The post-embedding finalization (saving vectors, sweeping stale files,
    rebuilding the keyword index, validating edges) has no progress counter, so
    a single message per step keeps the user informed while the index appears
    to sit at 100%.

    Returns:
        A callback suitable for ``IndexOrchestrator.index_codebase``'s
        ``status_callback``.
    """

    def report(message: str) -> None:
        print(f"Indexing: {message}...", file=sys.stderr)

    return report


def cmd_index(args: argparse.Namespace) -> int:
    """Run the ``index`` subcommand: build or update the code index.

    Resolves the codebase root, initialises components (optionally
    downloading the embedding model on first use), then runs the orchestrator
    to index, prune stale rows, or watch for changes based on the flags.

    Args:
        args: Parsed arguments; ``path``, ``context_dir``, ``force``,
            ``incremental``, ``watch``, ``exclude``, ``prune_stale``, and the
            include/exclude toggles are honoured.

    Returns:
        A process exit code: ``0`` on success, ``2`` for user/in-progress
        errors, ``1`` for unexpected failures.
    """
    _setup_logging(args.verbose)
    root_path = Path(args.path).resolve()
    if not root_path.is_dir():
        logger.error("Path does not exist: %s", root_path)
        return 1

    context_dir = root_path / ".context"
    if args.context_dir:
        context_dir = Path(args.context_dir).resolve()

    comps = _initialize_components(context_dir, settings=_settings_for_args(args), for_index=True)

    profile_error = _check_model_profile(comps["settings"])
    if profile_error is not None:
        return profile_error

    embedding_gen = comps["embedding_gen"]
    if not embedding_gen.is_available():
        from model2vec import StaticModel

        from code_search.engine.redactor import allow_downloads

        model_name = comps["settings"].embedding_model
        print(
            f"Vector model '{model_name}' is not available locally.",
            file=sys.stderr,
        )
        try:
            ans = input("  Download now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans in ("", "y", "yes"):
            print(f"Downloading {model_name}...")
            try:
                with allow_downloads():
                    StaticModel.from_pretrained(model_name)
                print("Model downloaded successfully.")
                embedding_gen._ensure_model()
            except Exception as exc:
                logger.warning("Model download failed: %s. Proceeding without vectors.", exc)
        else:
            logger.info("Proceeding without vector model. BM25-only search will be used.")

    exclusion_set: set[str] = set()
    if args.exclude:
        exclusion_set = set(p.strip() for p in args.exclude.split(",") if p.strip())

    status = comps["metadata"].get_index_status()
    if status == "indexing":
        # A killed or crashed run can leave this status behind. Treat it as
        # stale when no live lock exists (or the lock itself is stale) so the
        # next invocation can recover instead of being blocked forever.
        lock_path = context_dir / "index.lock"
        lock_is_live = False
        if lock_path.exists():
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
                lock_is_live = lock_age <= comps["settings"].lock_timeout
            except OSError:
                lock_is_live = False
        if lock_is_live:
            logger.error("Indexing already in progress")
            return 2
        logger.warning("Recovering from an interrupted index run")
        with suppress(OSError):
            lock_path.unlink()
        comps["metadata"].set_index_status("stale")

    if args.prune_stale:
        include_resources = args.include_resources
        if args.exclude_resources:
            include_resources = False
        res_exts = None
        if include_resources:
            if args.resource_extensions:
                res_exts = tuple(
                    e.strip() for e in args.resource_extensions.split(",") if e.strip()
                )
            else:
                res_exts = comps["settings"].resource_extensions
        summary = comps["orchestrator"].prune_stale_files(
            root_path=root_path,
            include_tests=args.include_tests,
            include_resources=include_resources,
            resource_extensions=res_exts,
            exclusion_patterns=exclusion_set,
        )
        print(f"Pruned stale index rows: {summary['pruned_files']} files")
        return 0

    try:
        include_resources = args.include_resources
        if args.exclude_resources:
            include_resources = False
        res_exts = None
        if include_resources:
            if args.resource_extensions:
                res_exts = tuple(
                    e.strip() for e in args.resource_extensions.split(",") if e.strip()
                )
            else:
                res_exts = comps["settings"].resource_extensions
        result = comps["orchestrator"].index_codebase(
            root_path=root_path,
            force=args.force,
            incremental=args.incremental,
            verbose=args.verbose,
            exclusion_patterns=exclusion_set,
            include_tests=args.include_tests,
            include_resources=include_resources,
            resource_extensions=res_exts,
            progress_callback=_make_index_progress_reporter(),
            status_callback=_make_index_status_reporter(),
        )
        print(
            f"Index complete: {result['total_files']} files, "
            f"{result['total_symbols']} symbols, "
            f"{result['total_chunks']} chunks in {result['duration_s']}s"
        )
        if result["languages"]:
            print(f"Languages: {', '.join(result['languages'])}")

        if args.watch:
            _start_watcher(root_path, exclusion_set, comps)

        return 0
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2
    except Exception as exc:
        logger.error("Index failed: %s", exc)
        with suppress(Exception):
            comps["metadata"].set_index_status("stale")
        return 1


def _start_watcher(
    root_path: Path,
    exclusion_set: set[str],
    comps: dict[str, Any],
) -> None:
    """Block running a file watcher that re-indexes changed files.

    Installs SIGINT/SIGTERM handlers that stop the watcher, then blocks in
    ``signal.pause`` so Ctrl+C performs a clean shutdown. On every change
    batch the watcher runs an incremental re-index.

    Args:
        root_path: The codebase root being watched.
        exclusion_set: Extra glob patterns excluded from re-indexing; the
            ``.context`` directory is always excluded.
        comps: The shared component registry (see ``_initialize_components``).
    """
    from code_search.engine.watcher import create_watcher

    def on_change(files: list[Path]) -> None:
        """Run an incremental re-index after the watcher detects changes."""
        logger.info("Detected %d changed files, re-indexing...", len(files))
        try:
            comps["orchestrator"].index_codebase(
                root_path=root_path,
                force=False,
                incremental=True,
                verbose=False,
                exclusion_patterns=exclusion_set,
            )
            logger.info("Incremental re-index complete")
        except Exception as exc:
            logger.error("Incremental re-index failed: %s", exc)

    watcher = create_watcher(
        root_path=root_path,
        index_callback=on_change,
        exclusion_patterns=exclusion_set | {".context"},
        settings=comps["settings"],
    )

    def handle_signal(signum: int, _frame: object) -> None:
        """Stop the watcher cleanly when SIGINT/SIGTERM is received."""
        logger.info("Shutting down file watcher (signal %d)...", signum)
        watcher.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    watcher.start()
    print("File watcher started. Press Ctrl+C to stop.")
    try:
        signal.pause()
    except KeyboardInterrupt:
        watcher.stop()


def _emit_stale_notice(signal: dict[str, Any]) -> None:
    """Print an advisory staleness notice to stderr (never stdout)."""
    if not signal.get("stale"):
        return
    count = signal.get("stale_change_count", 0)
    print(
        f"[stale index: {count} unindexed change(s) — index may be out of date; "
        "run 'code-search index --incremental']",
        file=sys.stderr,
    )


def _emit_reduced_notice(search_envelope: dict[str, Any]) -> None:
    """Print the one-line reduced cold-path notice for a warming response."""
    if search_envelope.get("ranked_path") != "lexical_reduced":
        return
    print("Warming the model in the background; results are lexical-only (reduced cold path).")


def _print_scope_override(scope: dict[str, Any]) -> None:
    """Print the CLI dialect of an actionable scope override to stderr.

    Suppressed when the override equals the effective scope, as on an
    inferred documentation search: the effective scope already includes
    documentation, so repeating ``--content all`` would contradict the
    response's own signal.
    """
    override = scope.get("override")
    if scope.get("signal") and override and override != scope.get("effective"):
        print(f"Override with: --content {override}", file=sys.stderr)


def _settings_for_args(args: argparse.Namespace) -> Settings:
    """Resolve settings with the runtime-profile CLI overrides applied.

    Args:
        args: Parsed arguments that may carry ``runtime_profile``,
            ``index_layout``, ``search_backend``, or ``freshness_mode``.

    Returns:
        The environment-derived settings with any explicit flags replacing the
        corresponding profile defaults.
    """
    from dataclasses import replace

    settings = Settings.with_context_dir(_resolve_context_dir(args))
    overrides: dict[str, Any] = {}
    for attr in ("runtime_profile", "index_layout", "search_backend", "freshness_mode"):
        value = getattr(args, attr, None)
        if value is not None:
            overrides[attr] = value
    if getattr(args, "no_graph", False):
        overrides["index_graph"] = False
    return replace(settings, **overrides) if overrides else settings


def _graph_not_indexed_message(comps: dict[str, Any]) -> str | None:
    """Return the graph_not_indexed explanation when the index has no graph."""
    if comps["metadata"].get("graph_indexed") == "false":
        return (
            "graph_not_indexed: this index was built with --no-graph; "
            "re-run 'code-search index --force' to populate call edges"
        )
    return None


def cmd_search(args: argparse.Namespace) -> int:
    """Run a natural-language search over the index.

    Attempts to forward to a running daemon first (unless ``--no-model``);
    otherwise initialises components, checks the index is ready, queries,
    reranks, redacts results, prints them (human or JSON), and records audit
    and metrics.

    Args:
        args: Parsed arguments; ``query``, ``limit``, ``language``,
            ``include_tests``, ``json``, ``no_model``, ``no_startup_check``,
            and ``regex`` are honoured.

    Returns:
        A process exit code: ``0`` on success, ``1`` when the index is not
        initialised.
    """
    import time

    profile_error = _check_model_profile(Settings.with_context_dir(_resolve_context_dir(args)))
    if profile_error is not None:
        return profile_error

    if getattr(args, "regex", False) and getattr(args, "mode", "ranked") != "exhaustive":
        print("--regex requires --mode exhaustive", file=sys.stderr)
        return 2

    external_warmup = False
    autostart_attempted = False
    if not getattr(args, "no_model", False):
        if not getattr(args, "no_startup_check", False):
            autostart_attempted = True
            external_warmup = _ensure_resident_service(args)
        forwarded = None
        if not getattr(args, "explain_ranking", False):
            forwarded = _try_forward_to_daemon(args)
        if forwarded is not None:
            return forwarded

    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(context_dir, settings=_settings_for_args(args))
    settings = comps["settings"]

    if external_warmup:
        # A resident service owns the single model load; this one-shot process
        # must not start a competing in-process load.
        comps["embedding_gen"].warmup_external = True

    if not getattr(args, "no_model", False):
        from code_search.engine.embeddings import check_index_model_compatibility

        try:
            check_index_model_compatibility(settings, comps["metadata"])
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if getattr(args, "no_model", False):
        from code_search.engine.search import HybridSearch

        print(
            "WARNING: --no-model: semantic/vector signals are disabled; "
            "search results are lexical-only and abstract-paraphrase queries "
            "will not be repaired.",
            file=sys.stderr,
        )
        comps["search"] = HybridSearch(
            comps["db"],
            comps["vector_index"],
            comps["embedding_gen"],
            settings,
            no_model=True,
        )

    explain_ranking = bool(getattr(args, "explain_ranking", False))
    if explain_ranking:
        from dataclasses import replace

        from code_search.engine.search import HybridSearch

        settings = replace(settings, score_breakdown=True)
        comps["settings"] = settings
        comps["search"] = HybridSearch(
            comps["db"],
            comps["vector_index"],
            comps["embedding_gen"],
            settings,
            no_model=bool(getattr(args, "no_model", False)),
        )

    status = comps["metadata"].get_index_status()
    if status not in ("ready",):
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    session_db = comps.get("session_db")
    if session_db is not None:
        repo_path = _resolve_context_dir(args).parent
        import contextlib

        with contextlib.suppress(Exception):
            session_db.track_git_changes(repo_path)

    search_envelope = comps["search"].search(
        query=args.query,
        limit=args.limit,
        language=args.language,
        include_tests=args.include_tests,
        mode=getattr(args, "mode", "ranked"),
        content=getattr(args, "content", None),
        matching=getattr(args, "matching", None),
        regex=getattr(args, "regex", False),
        allow_weak=bool(getattr(args, "allow_weak", False)),
    )
    raw_results = search_envelope["results"]
    mode = str(search_envelope.get("mode", "ranked"))
    if mode in ("exhaustive", "enumerate"):
        count_field = "total_count"
        total = int(search_envelope.get("total_count", len(raw_results)))
    else:
        count_field = "total_matches"
        total = int(search_envelope["total_matches"])
    truncated = bool(search_envelope["truncated"])
    vector_health = bool(search_envelope.get("vector_health"))
    envelope_confidence = search_envelope.get("confidence", "none")
    explanation = search_envelope.get("explanation")
    complete = search_envelope.get("complete")
    excluded = search_envelope.get("excluded")
    best_effort = bool(search_envelope.get("best_effort", False))

    from code_search.engine.response_service import build_response
    from code_search.engine.search import DEFAULT_CONTENT_SCOPE

    serving_envelope = build_response(
        raw_results,
        args.query,
        comps["index_change_detector"],
        content_scope=search_envelope.get("content") or DEFAULT_CONTENT_SCOPE,
        metadata_store=comps["metadata"],
        scope_signal=(search_envelope.get("scope") or {}).get("signal"),
    )

    from code_search.mcp.server import _freshness_signal

    performance_hint = (
        None if external_warmup or autostart_attempted else _daemon_performance_hint(context_dir)
    )

    def _envelope_out(results: list[dict[str, Any]]) -> dict[str, Any]:
        """Assemble the JSON envelope for the current search mode.

        Ranked envelopes report ``total_matches``/``best_effort`` and omit
        ``complete``; exhaustive/enumerate envelopes report the exact
        ``total_count`` and, when applicable, ``complete``/``excluded``.
        The serving envelope (index-change status + scope hint) is attached
        so the caller always sees an explanation when one is due.
        """
        from code_search.engine.response_service import relativize_results

        index_root = comps["metadata"].get("index_root") or str(context_dir.parent)
        out: dict[str, Any] = {
            "results": relativize_results(results, index_root),
            count_field: total,
            "truncated": truncated,
            "vector_health": vector_health,
            "mode": mode,
            "confidence": envelope_confidence,
            "explanation": explanation,
            "performance_hint": performance_hint,
            "freshness": _freshness_signal(comps),
        }
        if count_field != "total_matches":
            out["total_matches"] = total
        if search_envelope.get("token_savings") is not None:
            out["token_savings"] = search_envelope["token_savings"]
        if serving_envelope.get("envelope") is not None:
            out["envelope"] = serving_envelope["envelope"]
        out["index_status"] = serving_envelope["index_status"]
        out["index_changed"] = bool(serving_envelope.get("index_changed"))
        out["reload_required"] = bool(serving_envelope.get("reload_required"))
        if search_envelope.get("content") is not None:
            out["content"] = search_envelope["content"]
        for count_key in ("production_matches", "test_matches"):
            if search_envelope.get(count_key) is not None:
                out[count_key] = search_envelope[count_key]
        if search_envelope.get("scope") is not None:
            out["scope"] = search_envelope["scope"]
        if search_envelope.get("matching_semantics") is not None:
            out["matching_semantics"] = search_envelope["matching_semantics"]
        if search_envelope.get("query_time_ms") is not None:
            out["query_time_ms"] = search_envelope["query_time_ms"]
        if search_envelope.get("model_status") is not None:
            out["model_status"] = search_envelope["model_status"]
        if search_envelope.get("ranked_path") is not None:
            out["ranked_path"] = search_envelope["ranked_path"]
        if search_envelope.get("warmup_state") is not None:
            out["warmup_state"] = search_envelope["warmup_state"]
        if "degraded_reason" in search_envelope:
            out["degraded_reason"] = search_envelope["degraded_reason"]
        if search_envelope.get("no_match") is not None:
            out["no_match"] = search_envelope["no_match"]
        if complete is not None:
            out["complete"] = complete
        if excluded:
            out["excluded"] = excluded
        if best_effort:
            out["best_effort"] = True

        # Surface per-line occurrence metadata in exhaustive responses
        if mode == "exhaustive":
            if search_envelope.get("regex"):
                out["regex"] = True
            if search_envelope.get("pattern") is not None:
                out["pattern"] = search_envelope["pattern"]
            if search_envelope.get("occurrence_count") is not None:
                out["occurrence_count"] = search_envelope["occurrence_count"]
            if search_envelope.get("literal") is not None:
                out["literal"] = search_envelope["literal"]
            if search_envelope.get("occurrences_per_line") is not None:
                out["occurrences_per_line"] = search_envelope["occurrences_per_line"]
            if search_envelope.get("occurrence_line_numbers") is not None:
                out["occurrence_line_numbers"] = search_envelope["occurrence_line_numbers"]

        return out

    if not raw_results:
        engine_duration = search_envelope.get("query_time_ms")
        duration_ms = (
            round(engine_duration)
            if engine_duration is not None
            else int((time.monotonic() - start) * 1000)
        )
        if args.json:
            indent = (
                2
                if (getattr(args, "pretty", False) or not getattr(args, "compact", True))
                else None
            )
            print(json.dumps(_envelope_out([]), indent=indent, default=str))
        else:
            if explanation:
                rescued = ", ".join(explanation.get("rescued_tiers") or []) or "none"
                print(
                    f"No results found ({explanation.get('reason', 'no_match')}; "
                    f"rescued tiers: {rescued})."
                )
            else:
                print("No results found.")
            _print_match_breakdown(
                search_envelope.get("production_matches"),
                search_envelope.get("test_matches"),
                args.include_tests,
            )
            _emit_reduced_notice(search_envelope)
            if serving_envelope.get("envelope"):
                print(serving_envelope["envelope"], file=sys.stderr)
            _print_scope_override(search_envelope.get("scope") or {})
        comps["audit_db"].write_entry(
            query_type="search",
            query_summary=args.query[: settings.query_summary_length],
            result_count=0,
            duration_ms=duration_ms,
            redacted_count=0,
        )
        return 0

    reranked = comps["reranker"].rerank(
        raw_results, query_terms=_query_terms(args.query), query=args.query
    )

    redacted = comps["redactor"].redact_results(reranked)

    compact = bool(getattr(args, "compact", True))
    max_snippet_lines = getattr(args, "max_snippet_lines", None)
    paths_only = bool(getattr(args, "paths_only", False))
    if (
        not explain_ranking
        and (args.json or max_snippet_lines is not None or paths_only)
        and (compact or max_snippet_lines is not None or paths_only)
    ):
        from code_search.engine.response_service import compact_results

        redacted = compact_results(
            redacted,
            10 if max_snippet_lines is None else max_snippet_lines,
            paths_only=paths_only,
        )

    total_redacted = sum(r.get("redacted_count", 0) for r in redacted)
    engine_duration = search_envelope.get("query_time_ms")
    duration_ms = (
        round(engine_duration)
        if engine_duration is not None
        else int((time.monotonic() - start) * 1000)
    )

    if args.json:
        indent = 2 if (getattr(args, "pretty", False) or not compact) else None
        print(json.dumps(_envelope_out(redacted), indent=indent, default=str))
    else:
        index_root = comps["metadata"].get("index_root") or str(context_dir.parent)
        _print_search_results(redacted, settings, root=index_root)
        _print_match_breakdown(
            search_envelope.get("production_matches"),
            search_envelope.get("test_matches"),
            args.include_tests,
        )
        if explain_ranking:
            _print_ranking_explanation(redacted, root=index_root)
        print(f"Query time: {duration_ms} ms")
        _emit_reduced_notice(search_envelope)
        _emit_stale_notice(_freshness_signal(comps))
        if serving_envelope.get("envelope"):
            print(serving_envelope["envelope"], file=sys.stderr)
        _print_scope_override(search_envelope.get("scope") or {})
        if performance_hint:
            print(performance_hint)

    comps["audit_db"].write_entry(
        query_type="search",
        query_summary=args.query[: settings.query_summary_length],
        result_count=len(redacted),
        duration_ms=duration_ms,
        redacted_count=total_redacted,
    )

    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
        if total_redacted > 0:
            mc.record_redaction(total_redacted)

    return 0


def cmd_symbol(args: argparse.Namespace) -> int:
    """Look up a symbol by FQN and print its definition.

    Attempts daemon forwarding first. Resolves the symbol through the symbol
    store, redacts its source code, and prints the result in human or JSON
    form, handling ambiguous and not-found outcomes. Records audit and metrics.

    Args:
        args: Parsed arguments; ``fqn`` and ``json`` are honoured.

    Returns:
        A process exit code; ``0`` on success, ``1`` when the index is not
        initialised.
    """
    import time

    from code_search.mcp.server import _freshness_signal

    if not getattr(args, "no_startup_check", False):
        _ensure_resident_service(args)
    forwarded = _try_forward_to_daemon(args)
    if forwarded is not None:
        return forwarded

    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]

    status = comps["metadata"].get_index_status()
    if status not in ("ready",):
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    envelope = comps["symbol_store"].resolve_name(args.fqn)
    kind = envelope["kind"]
    symbol = envelope["symbol"]
    candidates = envelope["candidates"]
    index_root = comps["metadata"].get("index_root") or str(context_dir.parent)

    if kind == "ambiguous":
        duration_ms_entry = int((time.monotonic() - start) * 1000)
        if args.json:
            output_amb: dict[str, Any] = {
                "found": True,
                "ambiguous": True,
                "outcome": envelope.get("outcome", "ambiguous"),
                "symbol": None,
                "parent": None,
                "candidates": candidates,
                "freshness": _freshness_signal(comps),
            }
            print(json.dumps(output_amb, indent=2, default=str))
        else:
            _print_ambiguous_candidates(args.fqn, candidates, root=index_root)
            _emit_stale_notice(_freshness_signal(comps))
        comps["audit_db"].write_entry(
            query_type="get_symbol_definition",
            query_summary=args.fqn[: settings.query_summary_length],
            result_count=0,
            duration_ms=duration_ms_entry,
            redacted_count=0,
        )
        mc = comps.get("metrics_collector")
        if mc:
            mc.record_query(duration_ms_entry)
        return 0

    if symbol is None:
        duration_ms_entry = int((time.monotonic() - start) * 1000)
        suggestions = [c for c in candidates if c.get("suggestion")]
        if args.json:
            output_nf: dict[str, Any] = {
                "found": False,
                "outcome": envelope.get("outcome", "not_found"),
                "symbol": None,
                "candidates": candidates,
                "suggestion": bool(suggestions),
                "freshness": _freshness_signal(comps),
            }
            print(json.dumps(output_nf, indent=2, default=str))
        elif suggestions:
            best = suggestions[0]
            print(
                f"Symbol not found: {args.fqn}. Did you mean: {best.get('name')}? "
                f"(edit_distance {best.get('edit_distance')})"
            )
            from code_search.engine.graph_query import display_symbol, relative_display

            for c in suggestions:
                path = relative_display(c.get("file_path"), index_root)
                loc = f"{path}:{c['line_start']}-{c['line_end']}"
                print(f"  {display_symbol(c['fqn'] or '')} ({c['name']}, {c['kind']}) @ {loc}")
        else:
            print(f"Symbol not found: {args.fqn}")
            _emit_stale_notice(_freshness_signal(comps))
        comps["audit_db"].write_entry(
            query_type="get_symbol_definition",
            query_summary=args.fqn[: settings.query_summary_length],
            result_count=0,
            duration_ms=duration_ms_entry,
            redacted_count=0,
        )
        mc = comps.get("metrics_collector")
        if mc:
            mc.record_query(duration_ms_entry)
        return 0

    parent_info = None
    if symbol.get("parent_symbol_id") and symbol.get("parent_fqn"):
        parent_info = {
            "fqn": symbol["parent_fqn"],
            "name": symbol["parent_name"],
            "kind": symbol["parent_kind"],
        }

    source_code = symbol.get("source_code") or ""

    redacted_source, redacted_count = comps["redactor"].redact(source_code)

    if args.json:
        output_sym: dict[str, Any] = {
            "found": True,
            "outcome": envelope.get("outcome", "resolved"),
            "symbol": {
                "fqn": symbol["fqn"],
                "name": symbol["name"],
                "kind": symbol["kind"],
                "signature": symbol.get("signature"),
                "file_path": symbol["file_path"],
                "line_start": symbol["line_start"],
                "line_end": symbol["line_end"],
                "column_start": symbol["column_start"],
                "column_end": symbol["column_end"],
                "docstring": symbol.get("docstring") or "",
                "language": symbol["language"],
                "source_code": redacted_source,
            },
            "parent": parent_info,
            "freshness": _freshness_signal(comps),
            "query_time_ms": round((time.monotonic() - start) * 1000),
        }
        print(json.dumps(output_sym, indent=2, default=str))
    else:
        _print_symbol_details(symbol, parent_info, redacted_source, root=index_root)
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="get_symbol_definition",
        query_summary=args.fqn[: settings.query_summary_length],
        result_count=1 if symbol else 0,
        duration_ms=duration_ms,
        redacted_count=redacted_count,
    )

    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
        if redacted_count > 0:
            mc.record_redaction(redacted_count)

    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """Traverse the call graph for a symbol and print callers/callees.

    Attempts daemon forwarding first, otherwise reuses the MCP server's
    neighbor-payload builder so CLI and MCP output agree. Prints the graph in
    human or JSON form, then records audit and metrics.

    Args:
        args: Parsed arguments; ``fqn``, ``direction``, ``depth``,
            ``transitive``, and ``json`` are honoured.

    Returns:
        A process exit code; ``0`` on success, ``1`` when the index is not
        initialised.
    """
    import time

    if not getattr(args, "no_startup_check", False):
        _ensure_resident_service(args)
    forwarded = _try_forward_to_daemon(args)
    if forwarded is not None:
        return forwarded

    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]

    status = comps["metadata"].get_index_status()
    if status not in ("ready",):
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if args.json:
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    from code_search.mcp.server import _call_neighbors_payload, _freshness_signal

    direction = args.direction
    depth = min(args.depth, settings.max_graph_depth)
    payload = _call_neighbors_payload(
        comps["symbol_store"],
        comps["edge_store"],
        args.fqn,
        direction,
        depth,
        comps.get("freshness"),
        args.transitive,
        comps["db"],
    )
    data = json.loads(payload)
    symbol = data.get("symbol")
    callers = data.get("callers") or []
    callees = data.get("callees") or []
    index_root = comps["metadata"].get("index_root") or str(context_dir.parent)
    from code_search.engine.graph_query import edge_resolution_stats

    coverage = edge_resolution_stats(comps["db"])
    data["coverage"] = coverage
    unresolved: list[dict[str, Any]] = []
    if getattr(args, "explain_unresolved", False) and symbol is not None:
        with comps["db"].connect() as conn:
            rows = conn.execute(
                "SELECT edge_type, target_raw FROM graph_edges "
                "WHERE source_symbol_id = ? AND resolved = 0 ORDER BY edge_type, target_raw;",
                (symbol.get("id"),),
            ).fetchall()
        unresolved = [
            {"edge_type": row["edge_type"], "target_raw": row["target_raw"]} for row in rows
        ]
        data["unresolved"] = unresolved

    if args.json:
        data.setdefault("freshness", _freshness_signal(comps))
        data["query_time_ms"] = round((time.monotonic() - start) * 1000)
        print(json.dumps(data, indent=2, default=str))
    elif direction == "implements":
        _print_implementations(data, args.fqn, root=index_root)
        _emit_stale_notice(_freshness_signal(comps))
    elif symbol is None and data.get("candidates"):
        _print_ambiguous_candidates(args.fqn, data.get("candidates") or [], root=index_root)
        _emit_stale_notice(_freshness_signal(comps))
    elif symbol is None:
        print(f"Symbol not found: {args.fqn}")
        _emit_stale_notice(_freshness_signal(comps))
    else:
        _print_graph_results(symbol, callers, callees, root=index_root)
        for edge_type, stats in coverage.items():
            print(
                f"{edge_type}: {stats['ratio'] / 10:.0f}% resolved "
                f"({stats['resolved']}/{stats['total']})"
            )
        if unresolved:
            print("Unresolved references:")
            for item in unresolved:
                print(f"  {item['edge_type']}: {item['target_raw']}")
        elif (
            symbol is not None
            and not callers
            and not callees
            and any(stats["unresolved"] for stats in coverage.values())
        ):
            print(
                "No callers/callees resolved; run with --explain-unresolved to list "
                "unresolved raw targets."
            )
        _emit_stale_notice(_freshness_signal(comps))

    if direction == "implements":
        total_results = len(data.get("implementations") or [])
    else:
        total_results = len(callers) + len(callees)
    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="get_call_neighbors",
        query_summary=args.fqn[: settings.query_summary_length],
        result_count=total_results,
        duration_ms=duration_ms,
        redacted_count=0,
    )

    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)

    return 0


def cmd_implementations(args: argparse.Namespace) -> int:
    """Find the static implementations of an interface member or type.

    Attempts daemon forwarding first, otherwise calls the shared engine rule so
    CLI output matches the MCP tool for the same request. Prints the
    implementations (relationship, inherited label, location) in human mode, or
    the shared envelope with freshness and timing in ``--json`` mode, then
    records the ``get_implementations`` audit entry.

    Args:
        args: Parsed arguments; ``fqn`` and ``json`` are honoured.

    Returns:
        A process exit code; ``0`` on success, ``1`` when the index is not
        initialised.
    """
    import time

    from code_search.mcp.server import _freshness_signal

    if not getattr(args, "no_startup_check", False):
        _ensure_resident_service(args)
    forwarded = _try_forward_to_daemon(args)
    if forwarded is not None:
        return forwarded

    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]

    status = comps["metadata"].get_index_status()
    if status not in ("ready",):
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    from code_search.engine.implementations import find_implementations

    result = find_implementations(comps["symbol_store"], comps["edge_store"], args.fqn)
    implementations = result.get("implementations") or []
    index_root = comps["metadata"].get("index_root") or str(context_dir.parent)

    if args.json:
        result["freshness"] = _freshness_signal(comps)
        result["query_time_ms"] = round((time.monotonic() - start) * 1000)
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_implementations(result, args.fqn, root=index_root)
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="get_implementations",
        query_summary=args.fqn[: settings.query_summary_length],
        result_count=len(implementations),
        duration_ms=duration_ms,
        redacted_count=0,
    )

    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)

    return 0


def _graph_query_service(comps: dict[str, Any]) -> Any:
    """Build a graph-query service over the initialized components."""
    from code_search.engine.graph_query import GraphQueryService

    return GraphQueryService(
        comps["db"],
        comps["symbol_store"],
        comps["edge_store"],
        comps["search"],
        comps.get("settings"),
        reranker=comps.get("reranker"),
    )


def _parse_edge_types(value: str | None) -> set[str] | None:
    """Parse a comma-separated ``--edge-types`` value, or return ``None``."""
    if not value:
        return None
    parsed = {part.strip().upper() for part in value.split(",") if part.strip()}
    return parsed or None


def _git_changed_files(root: Path, ref: str) -> list[str]:
    """Return working-tree paths changed relative to *ref*.

    Raises:
        RuntimeError: When git is unavailable or *ref* cannot be resolved.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", ref],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git is unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git diff failed for {ref!r}: {detail}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def cmd_find_related(args: argparse.Namespace) -> int:
    """Return chunks semantically related to the chunk at a file/line anchor.

    Shares the MCP ``find_related`` payload builder so both surfaces report the
    same neighbours, status, and freshness. Text output renders paths relative
    to the indexed root; JSON keeps the same portable spelling.

    Args:
        args: Parsed arguments; ``file_path``, ``line``, ``limit``, and
            ``json`` are honoured.

    Returns:
        A process exit code: ``0`` on success, ``1`` when the index is not
        initialised.
    """
    if not getattr(args, "no_startup_check", False):
        _ensure_resident_service(args)
    forwarded = _try_forward_to_daemon(args)
    if forwarded is not None:
        return forwarded

    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(context_dir, settings=_settings_for_args(args))
    settings = comps["settings"]
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    from code_search.engine.response_service import relativize_results
    from code_search.mcp.server import _find_related_payload, _freshness_signal

    payload = json.loads(_find_related_payload(comps, args.file_path, args.line, args.limit))
    root = comps["metadata"].get("index_root") or str(context_dir.parent)
    results = relativize_results(payload.get("results") or [], root)
    payload["results"] = results

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    elif payload.get("error"):
        print(payload["error"], file=sys.stderr)
    else:
        header = f"{'Similarity':<11} {'File':<40} {'Symbol':<35}"
        print(header)
        print("-" * len(header))
        for result in results:
            location = f"{result['file_path']}:{result['line_start']}-{result['line_end']}"
            print(
                f"  {result.get('similarity', 0.0):.3f}     "
                f"{location:<40} {result.get('fqn') or '':<35}"
            )
        if payload.get("explanation"):
            print(payload["explanation"], file=sys.stderr)
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="find_related",
        query_summary=f"{args.file_path}:{args.line}"[: settings.query_summary_length],
        result_count=len(results),
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Answer a natural-language question by traversing the code graph."""
    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if getattr(args, "json", False):
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    service = _graph_query_service(comps)
    answer = service.query(
        args.question,
        depth=args.depth,
        max_nodes=args.max_nodes,
        edge_types=_parse_edge_types(args.edge_types),
        token_budget=args.token_budget,
        include_external=getattr(args, "include_externals", False),
    )
    from code_search.engine.graph_query import render_query_text
    from code_search.mcp.server import _freshness_signal

    if args.json:
        payload = answer.as_dict()
        payload["freshness"] = _freshness_signal(comps)
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        print(json.dumps(payload, indent=2, default=str))
    else:
        root = comps["metadata"].get("index_root") or str(context_dir.parent)
        print(render_query_text(answer, root=root))
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="query_graph",
        query_summary=args.question[: settings.query_summary_length],
        result_count=len(answer.nodes),
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    """Print the shortest path between two symbols."""
    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if getattr(args, "json", False):
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    service = _graph_query_service(comps)
    answer = service.shortest_path(
        args.source,
        args.target,
        undirected=args.undirected,
        max_hops=args.max_hops,
        edge_types=_parse_edge_types(args.edge_types),
    )
    from code_search.engine.graph_query import render_path_text
    from code_search.mcp.server import _freshness_signal

    if args.json:
        payload = answer.as_dict()
        payload["freshness"] = _freshness_signal(comps)
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render_path_text(answer))
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="shortest_path",
        query_summary=f"{args.source} -> {args.target}"[: settings.query_summary_length],
        result_count=len(answer.hops),
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0 if answer.outcome in ("resolved", "trivial") else 2


def cmd_explain(args: argparse.Namespace) -> int:
    """Print a symbol's metadata, relations, rationale, and linked docs."""
    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if getattr(args, "json", False):
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    service = _graph_query_service(comps)
    answer = service.explain(
        args.symbol,
        depth=args.depth,
        relations=_parse_edge_types(args.relations),
    )
    from code_search.engine.graph_query import render_explain_text
    from code_search.mcp.server import _freshness_signal

    if args.json:
        payload = answer.as_dict()
        payload["freshness"] = _freshness_signal(comps)
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        print(json.dumps(payload, indent=2, default=str))
    else:
        root = comps["metadata"].get("index_root") or str(context_dir.parent)
        print(render_explain_text(answer, root=root))
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="explain_symbol",
        query_summary=args.symbol[: settings.query_summary_length],
        result_count=1 if answer.symbol else 0,
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0 if answer.outcome == "resolved" else 2


def cmd_affected(args: argparse.Namespace) -> int:
    """Report symbols impacted by changed files (git diff or explicit paths)."""
    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    settings = comps["settings"]
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    index_root = comps["metadata"].get("index_root") or str(context_dir.parent)
    changed = list(args.paths)
    if args.since:
        try:
            changed.extend(_git_changed_files(Path(index_root), args.since))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if not changed:
        print("No changed files: pass paths or --since <git-ref>.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if getattr(args, "json", False):
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    service = _graph_query_service(comps)
    answer = service.impact(changed, depth=args.depth)
    from code_search.engine.graph_query import render_impact_text
    from code_search.mcp.server import _freshness_signal

    if args.json:
        payload = answer.as_dict()
        payload["freshness"] = _freshness_signal(comps)
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render_impact_text(answer, root=index_root))
        _emit_stale_notice(_freshness_signal(comps))

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="get_impact",
        query_summary=", ".join(changed)[: settings.query_summary_length],
        result_count=len(answer.impacted),
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Generate a deterministic architecture report for the indexed graph."""
    start = time.monotonic()
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )
    if comps["metadata"].get_index_status() != "ready":
        print("Index not initialized. Run 'code-search index' first.", file=sys.stderr)
        return 1

    graph_missing = _graph_not_indexed_message(comps)
    if graph_missing is not None:
        if getattr(args, "json", False):
            print(json.dumps({"error": "graph_not_indexed", "message": graph_missing}))
        else:
            print(graph_missing, file=sys.stderr)
        return 1

    service = _graph_query_service(comps)
    report = service.architecture_report(
        top_n=args.top,
        max_communities=args.max_communities,
    )
    from code_search.engine.graph_query import render_architecture_markdown

    if args.json:
        payload = report.as_dict()
        payload["query_time_ms"] = round((time.monotonic() - start) * 1000, 1)
        print(json.dumps(payload, indent=2, default=str))
    else:
        markdown = render_architecture_markdown(report)
        if args.output:
            Path(args.output).write_text(markdown, encoding="utf-8")
            print(f"Wrote {args.output}")
        else:
            print(markdown)

    duration_ms = int((time.monotonic() - start) * 1000)
    comps["audit_db"].write_entry(
        query_type="map",
        query_summary=f"top={args.top}",
        result_count=len(report.god_nodes),
        duration_ms=duration_ms,
        redacted_count=0,
    )
    mc = comps.get("metrics_collector")
    if mc:
        mc.record_query(duration_ms)
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """Print index health and usage metrics in the requested format.

    Gathers index metadata plus audit/query statistics and renders them as
    human-readable text, JSON, or Prometheus exposition format.

    Args:
        args: Parsed arguments; ``format`` selects the output style.

    Returns:
        ``0`` on success.
    """
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    comps = _initialize_components(
        context_dir, settings=_settings_for_args(args), load_vectors=False
    )

    meta = comps["metadata"].get_all()

    if args.format == "json":
        meta["metrics"] = _collect_metrics(comps)
        print(json.dumps(meta, indent=2, default=str))
    elif args.format == "prometheus":
        _print_prometheus_metrics(meta, comps)
    else:
        _print_human_metrics(meta, comps)
    return 0


def _human_bytes(value: int) -> str:
    """Format a byte count as a compact human-readable string."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _index_age_seconds(metadata: Any) -> float | None:
    """Return the seconds since ``last_indexed_at``, or ``None`` when unknown."""
    from datetime import UTC, datetime

    raw = metadata.get("last_indexed_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def cmd_start(args: argparse.Namespace) -> int:
    """Alias for ``daemon start``."""
    args.daemon_action = "start"
    return cmd_daemon(args)


def cmd_status(args: argparse.Namespace) -> int:
    """Alias for ``daemon status``."""
    args.daemon_action = "status"
    return cmd_daemon(args)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report index age, model availability, daemon state, and index size."""
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    settings = _settings_for_args(args)
    comps = _initialize_components(context_dir, settings=settings, load_vectors=False)
    metadata = comps["metadata"]
    from code_search.engine.daemon import daemon_status

    status = daemon_status(context_dir)
    age = _index_age_seconds(metadata)
    graph_path = context_dir / "graph.db"
    total = graph_path.stat().st_size if graph_path.is_file() else 0
    payload = {
        "context_dir": str(context_dir),
        "index_status": metadata.get_index_status(),
        "index_age_s": round(age, 1) if age is not None else None,
        "index_bytes": total,
        "profile": settings.runtime_profile,
        "layout": metadata.get("index_layout") or settings.index_layout,
        "daemon": status,
        "model_available": comps["embedding_gen"].is_available(),
        "graph_indexed": metadata.get("graph_indexed") != "false",
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Print the effective runtime profile, index layout, and disk footprint.

    Reports the profile selection reason, the recorded layout/backend, index
    age, database and vector sizes, and the largest content tables so the
    storage experiments have a reproducible measurement surface.

    Args:
        args: Parsed arguments; ``format`` selects ``text`` or ``json``.

    Returns:
        ``0`` on success.
    """
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    settings = _settings_for_args(args)
    comps = _initialize_components(context_dir, settings=settings, load_vectors=False)
    metadata = comps["metadata"]
    db = comps["db"]

    recorded_layout = metadata.get("index_layout") or settings.index_layout
    graph_path = context_dir / "graph.db"
    if not graph_path.is_file():
        graph_path = Path(settings.context_dir) / "graph.db"
    vector_bin = context_dir / "vectors.v2.bin"
    if not vector_bin.is_file():
        vector_bin = context_dir / "vectors.bin"
    vector_meta = context_dir / "vectors.v2.meta"
    if not vector_meta.is_file():
        vector_meta = context_dir / "vectors.meta.json"

    counts: dict[str, int] = {}
    try:
        with db.connect() as conn:
            for table in ("code_chunks", "symbols", "graph_edges", "module_edges", "chunks_fts"):
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()
                counts[table] = int(row["n"]) if row is not None else 0
    except Exception as exc:
        logger.debug("stats table counts unavailable: %s", exc)

    age = _index_age_seconds(metadata)
    payload: dict[str, Any] = {
        "profile": settings.runtime_profile,
        "profile_reason": settings.profile_reason(),
        "layout": recorded_layout,
        "backend": settings.search_backend,
        "freshness_mode": settings.freshness_mode,
        "index_status": metadata.get_index_status(),
        "index_age_s": round(age, 1) if age is not None else None,
        "graph_db_bytes": graph_path.stat().st_size if graph_path.is_file() else 0,
        "vectors_bin_bytes": vector_bin.stat().st_size if vector_bin.is_file() else 0,
        "vectors_meta_bytes": vector_meta.stat().st_size if vector_meta.is_file() else 0,
        "counts": counts,
        "thresholds": {
            "compact_max_chunks": settings.compact_max_chunks,
            "compact_max_index_mb": settings.compact_max_index_mb,
            "memory_budget_mb": settings.memory_budget_mb,
        },
    }
    payload["total_bytes"] = (
        payload["graph_db_bytes"] + payload["vectors_bin_bytes"] + payload["vectors_meta_bytes"]
    )

    if getattr(args, "format", "text") == "json":
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f"Profile:        {payload['profile']} ({payload['profile_reason']})")
    print(f"Layout:         {payload['layout']}")
    print(f"Backend:        {payload['backend']}")
    print(f"Freshness:      {payload['freshness_mode']}")
    print(f"Index status:   {payload['index_status']}")
    if age is not None:
        print(f"Index age:      {age:.0f}s")
    print(f"Total size:     {_human_bytes(int(payload['total_bytes']))}")
    print(f"  graph.db:     {_human_bytes(int(payload['graph_db_bytes']))}")
    print(f"  vectors.bin:  {_human_bytes(int(payload['vectors_bin_bytes']))}")
    print(f"  vectors.meta: {_human_bytes(int(payload['vectors_meta_bytes']))}")
    for table, count in counts.items():
        print(f"  {table}: {count:,}")
    return 0


def _collect_metrics(comps: dict[str, Any]) -> dict[str, Any]:
    """Aggregate index, audit, and query metrics into a single dict.

    Args:
        comps: The shared component registry (see ``_initialize_components``).

    Returns:
        A flat dict of metric names to values for JSON output.
    """
    audit_db: AuditDatabase = comps["audit_db"]
    meta = comps["metadata"].get_all()
    entries = audit_db.count_entries()
    redacted_total = 0
    for entry in audit_db.get_entries(limit=1000):
        redacted_total += entry["redacted_count"]
    mc = comps.get("metrics_collector")
    latency_stats = mc.get_latency_stats() if mc else {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    return {
        "audit_entries": entries,
        "total_redacted": redacted_total,
        "latency_ms": latency_stats,
        "total_queries": mc.get_total_queries() if mc else 0,
        "total_metrics_redactions": mc.get_total_redactions() if mc else 0,
        "last_indexed": meta.get("last_indexed_at"),
        "index_status": meta.get("index_status", "unknown"),
        "index_version": meta.get("index_version"),
        "search_modes_enabled": meta.get("search_modes_enabled", "ranked"),
        "total_files": meta.get("total_files"),
        "total_symbols": meta.get("total_symbols"),
        "total_chunks": meta.get("total_chunks"),
        "fts_chunks": meta.get("fts_chunks"),
        "vector_model_available": meta.get("vector_model_available"),
        "vector_model_loaded": meta.get("vector_model_loaded"),
        "supported_languages": meta.get("supported_languages"),
        "test_files_included": meta.get("test_files_included"),
    }


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the MCP server over stdio (``serve`` subcommand).

    Initialises components, creates the MCP server, and blocks serving on
    ``stdio`` inside an air-gap enforcement context so no network calls are
    made while serving.

    Args:
        args: Parsed arguments; ``context_dir`` is honoured.

    Returns:
        ``0`` after the server shuts down.
    """
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    import os

    os.environ.setdefault("CODE_SEARCH_CONTEXT_DIR", str(context_dir))

    comps = _initialize_components(context_dir)

    from code_search.engine.redactor import air_gap_enforcement
    from code_search.mcp.server import create_server

    # Warm the model in the background so the first tool call during warmup is
    # served from the reduced lexical path instead of blocking on the load.
    begin_warmup = getattr(comps.get("embedding_gen"), "begin_warmup", None)
    if callable(begin_warmup):
        begin_warmup()

    server = create_server(comps)
    with air_gap_enforcement():
        server.run(transport="stdio")
    return 0


def _resolve_context_dir(args: argparse.Namespace) -> Path:
    """Resolve the context directory from args, env, or the default.

    Precedence: the ``--context-dir`` argument, then the
    ``CODE_SEARCH_CONTEXT_DIR`` environment variable, then a literal scan of
    ``sys.argv``, then ``.context`` relative to the current directory.

    Args:
        args: Parsed arguments, checked for a ``context_dir`` attribute.

    Returns:
        The resolved absolute context directory path.
    """
    if hasattr(args, "context_dir") and args.context_dir:
        return Path(args.context_dir).resolve()
    import os

    env_dir = os.environ.get("CODE_SEARCH_CONTEXT_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    try:
        idx = sys.argv.index("--context-dir")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1]).resolve()
    except ValueError:
        pass
    return Path(".context").resolve()


def _query_terms(query: str) -> list[str] | None:
    """Return the queried symbol identifier for selective definition boosting.

    A single symbol-like identifier (e.g. ``is_token_valid``) is returned so
    the reranker boosts only the chunk defining that symbol; natural-language
    queries return ``None`` to keep the legacy blanket boost.
    """
    from code_search.engine.search import query_symbol_identifier

    identifier = query_symbol_identifier(query)
    return [identifier] if identifier else None


def _print_search_results(
    results: list[dict[str, Any]],
    settings: Settings | None = None,
    root: str | Path | None = None,
) -> None:
    """Print search results as a human-readable aligned table.

    Low-confidence-band results carry a ``[borderline]`` marker so consumers
    know to verify them. Paths and symbols are shown relative to the indexed
    root so the table stays readable; JSON output keeps the absolute paths.

    Args:
        results: The search result dicts, already reranked and redacted.
        settings: Runtime settings used for the snippet length; defaults to
            :func:`code_search.engine.config.Settings.from_env` when omitted.
        root: Indexed repository root used to relativize paths. Absolute paths
            are left unchanged when omitted or when a result lies outside it.
    """
    from code_search.engine.graph_query import display_symbol, relative_display

    settings = settings or Settings.from_env()
    snippet_len = settings.snippet_length
    header = f"{'Score':<7} {'File':<35} {'Symbol':<35} Snippet"
    print(header)
    print("-" * len(header))
    for r in results:
        score = f"{r['score']:.2f}"
        file_path = relative_display(r.get("file_path"), root)
        file_loc = f"{file_path}:{r['line_start']}-{r['line_end']}"
        fqn = display_symbol(r.get("fqn") or "")
        snippet = (r.get("content") or "")[:snippet_len].replace("\n", " ")
        test_tag = " [test file]" if r.get("is_test_file") else ""
        redacted_tag = f" [{r['redacted_count']} redacted]" if r.get("redacted_count") else ""
        borderline_tag = " [borderline]" if r.get("borderline") else ""
        print(
            f"  {score}  {file_loc:<35} {fqn:<35} {snippet}{test_tag}{redacted_tag}{borderline_tag}"
        )


def _print_match_breakdown(
    production_matches: int | None,
    test_matches: int | None,
    include_tests: bool,
) -> None:
    """Print the production/test match split when the envelope reports it.

    Ranked envelopes carry both counts, so hidden test files never change the
    total silently. The split is printed even when no test chunk matched, and
    the ``--include-tests`` hint appears only when tests are actually hidden.
    Both the local and daemon-forwarded human paths call this so they render
    identically.

    Args:
        production_matches: Production chunk count, or ``None`` when unknown.
        test_matches: Test chunk count, or ``None`` when unknown.
        include_tests: Whether test chunks were requested.
    """
    if production_matches is None or test_matches is None:
        return
    if not production_matches and not test_matches:
        return
    hidden = "" if include_tests or not test_matches else " (hidden; use --include-tests)"
    print(f"Matches: {production_matches} production + {test_matches} test{hidden}")


def _print_ranking_explanation(
    results: list[dict[str, Any]],
    root: str | Path | None = None,
) -> None:
    """Print per-result score components for ``--explain-ranking``.

    Shows the lexical, dense, and fused scores, then the class/content
    multipliers and additive boosts that produced the final score. The output
    is intentionally compact: one line per result so a ranking decision can be
    audited without dumping the full JSON envelope.

    Args:
        results: Reranked search results carrying ``score_sources``.
        root: Indexed repository root used to relativize paths.
    """
    from code_search.engine.graph_query import relative_display

    print("\nRanking explanation")
    for rank, result in enumerate(results, start=1):
        sources = result.get("score_sources") or {}
        multipliers = sources.get("multipliers") or {}
        additive = sources.get("additive") or {}
        location = relative_display(result.get("file_path"), root)
        print(
            f"  {rank:>2}. score={result.get('score', 0.0):.4f} "
            f"fused={sources.get('fused', 0.0):.4f} "
            f"bm25={sources.get('bm25', 0.0):.4f} "
            f"vector={sources.get('vector', 0.0):.4f} "
            f"mult(class={multipliers.get('rank_class', 1.0):.3f},"
            f"content={multipliers.get('content', 1.0):.3f},"
            f"test={multipliers.get('test_noise', 1.0):.3f},"
            f"infra={multipliers.get('infra', 1.0):.3f}) "
            f"add(exact={additive.get('exact_match', 0.0):.3f},"
            f"lift={additive.get('min_vector_lift', 0.0):.3f}) "
            f"{location}"
        )


def _print_symbol_details(
    symbol: dict[str, Any],
    parent_info: dict[str, Any] | None,
    source_code: str = "",
    root: str | Path | None = None,
) -> None:
    """Print a symbol's identity, parent, and (redacted) source code.

    Args:
        symbol: The resolved symbol dict.
        parent_info: Optional ``{fqn, name, kind}`` dict for the enclosing
            parent symbol, or ``None``.
        source_code: The redacted source text to print, if any.
        root: Indexed repository root used to relativize the file location.
    """
    from code_search.engine.graph_query import display_symbol, relative_display

    print(f"Symbol: {symbol['name']}")
    print(f"  FQN:    {display_symbol(symbol['fqn'])}")
    if symbol.get("signature"):
        print(f"  Sig:    {symbol['signature']}")
    print(f"  Kind:   {symbol['kind']}")
    location = relative_display(symbol.get("file_path"), root)
    print(f"  File:   {location}:{symbol['line_start']}-{symbol['line_end']}")
    if parent_info:
        print(f"  Parent: {display_symbol(parent_info['fqn'])} ({parent_info['kind']})")
    if source_code:
        print(f"\n{source_code}")


def _print_ambiguous_candidates(
    symbol: str,
    candidates: list[dict[str, Any]],
    root: str | Path | None = None,
) -> None:
    """Print a ranked, best-first ambiguous-symbol list with evidence.

    Args:
        symbol: The queried symbol name.
        candidates: Ranked candidate definition dicts to display.
        root: Indexed repository root used to relativize locations.
    """
    from code_search.engine.graph_query import display_symbol, relative_display

    print(f"Symbol '{symbol}' is ambiguous — {len(candidates)} candidates (best first):")
    for index, c in enumerate(candidates[:10], start=1):
        loc = relative_display(c.get("file_path"), root)
        loc = f"{loc}:{c['line_start']}-{c['line_end']}"
        print(f"  {index}. {display_symbol(c['fqn'] or '')} ({c['name']}, {c['kind']}) @ {loc}")
        evidence = c.get("evidence") or []
        if evidence:
            print(f"     evidence: {', '.join(str(e) for e in evidence)}")


def _print_graph_results(
    symbol: dict[str, Any],
    callers: list[dict[str, Any]],
    callees: list[dict[str, Any]],
    root: str | Path | None = None,
) -> None:
    """Print a call graph as caller/callee lists with arrow glyphs.

    Args:
        symbol: The graph root symbol dict.
        callers: Dicts describing symbols that call the root.
        callees: Dicts describing symbols the root calls.
        root: Indexed repository root used to relativize locations.
    """
    from code_search.engine.graph_query import display_symbol, relative_display

    print(f"Call graph for: {display_symbol(symbol['fqn'])}\n")
    if callers:
        print(f"Callers ({len(callers)}):")
        for c in callers:
            sig = _compact_signature(c.get("target_signature"))
            location = relative_display(c.get("file_path"), root)
            print(f"  \u2190 {display_symbol(c['fqn']):<45} {location}:{c['line_start']}{sig}")
    if callees:
        print(f"Callees ({len(callees)}):")
        for c in callees:
            sig = _compact_signature(c.get("target_signature"))
            location = relative_display(c.get("file_path"), root)
            print(f"  \u2192 {display_symbol(c['fqn']):<45} {location}:{c['line_start']}{sig}")


def _print_implementations(
    result: dict[str, Any],
    query: str,
    root: str | Path | None = None,
) -> None:
    """Print an implementation-lookup result in human-readable form.

    Renders the four outcomes honestly: resolved implementations with their
    relationship, inherited label, and navigable location; an ambiguous
    candidate list; a not-found message; or the explicit no-static explanation.

    Args:
        result: The shared implementation envelope from ``find_implementations``.
        query: The caller-supplied reference (for headings and messages).
        root: Indexed repository root used to relativize locations.
    """
    from code_search.engine.graph_query import display_symbol, relative_display

    outcome = result.get("outcome")
    if outcome == "ambiguous":
        _print_ambiguous_candidates(query, result.get("candidates") or [], root=root)
        return
    if outcome == "not_found":
        print(f"Symbol not found: {query}")
        return
    if outcome == "no_static_implementation":
        print(result.get("explanation") or "No static implementation found")
        return
    implementations = result.get("implementations") or []
    declaring = result.get("declaring_type") or {}
    declaring_fqn = display_symbol(str(declaring.get("fqn") or ""))
    print(f"Implementations of {query} via {declaring_fqn} ({len(implementations)}):")
    for impl in implementations:
        type_row = impl.get("type") or {}
        site = impl.get("site") or {}
        relationship = impl.get("relationship")
        inherited = site.get("inherited")
        label = "inherited" if inherited else "declared"
        type_path = relative_display(type_row.get("file_path"), root)
        loc_type = f"{type_path}:{type_row.get('line_start')}"
        print(f"  {display_symbol(str(type_row.get('fqn') or ''))}  ({relationship}, {label})")
        if site:
            site_path = relative_display(site.get("file_path"), root)
            loc_site = f"{site_path}:{site.get('line_start')}"
            origin = site.get("declaring_type_fqn") if inherited else site.get("fqn")
            print(f"    {display_symbol(str(origin or ''))} @ {loc_site}")
        else:
            print(f"    {loc_type}")


def _compact_signature(sig: dict[str, Any] | None) -> str:
    """Render a signature dict as ``(a, b)`` or an empty string."""
    if not sig:
        return ""
    return "(" + ", ".join(sig.get("param_types") or []) + ")"


def _print_human_metrics(meta: dict[str, str], comps: dict[str, Any]) -> None:
    """Print index health plus audit statistics as readable text.

    Args:
        meta: Index metadata dict from ``metadata.get_all()``.
        comps: The shared component registry, used for the audit database.
    """
    print("Index Health:")
    print(f"  Status:               {meta.get('index_status', 'unknown')}")
    print(f"  Schema Version:       {meta.get('index_version', 'N/A')}")
    print(f"  Files Indexed:        {meta.get('total_files', 'N/A')}")
    print(f"  Symbols Indexed:      {meta.get('total_symbols', 'N/A')}")
    print(f"  Chunks Indexed:       {meta.get('total_chunks', 'N/A')}")
    print(f"  FTS Chunks:           {meta.get('fts_chunks', 'N/A')}")
    print(f"  Languages:            {meta.get('languages', 'N/A')}")
    print(f"  Last Indexed:         {meta.get('last_indexed_at', 'N/A')}")
    print(f"  Vector Model Avail:   {meta.get('vector_model_available', 'N/A')}")
    print(f"  Test Files Included:  {meta.get('test_files_included', 'N/A')}")
    print(f"  Search Modes:         {meta.get('search_modes_enabled', 'ranked')}")
    audit_db: AuditDatabase = comps["audit_db"]
    entries = audit_db.count_entries()
    print(f"  Audit Entries:        {entries}")
    redacted_total = sum(r["redacted_count"] for r in audit_db.get_entries(limit=1000))
    print(f"  Secret Redactions:    {redacted_total}")


def cmd_list_languages(args: argparse.Namespace) -> int:
    """Print the supported languages with their extensions and grammars."""
    _setup_logging(args.verbose)
    from code_search.engine.parser import LANGUAGE_GRAMMAR_MAP, LANGUAGE_MAP, SUPPORTED_LANGUAGES

    ext_by_lang: dict[str, list[str]] = {}
    for ext, lang in LANGUAGE_MAP.items():
        ext_by_lang.setdefault(lang, []).append(ext)
    print(f"Supported languages ({len(SUPPORTED_LANGUAGES)}):")
    for lang in sorted(SUPPORTED_LANGUAGES):
        exts = ", ".join(sorted(ext_by_lang.get(lang, [])))
        grammar = LANGUAGE_GRAMMAR_MAP.get(lang, "N/A")
        print(f"  {lang:<12} {exts:<22} {grammar}")
    return 0


def _print_prometheus_metrics(meta: dict[str, str], comps: dict[str, Any]) -> None:
    """Print index and audit metrics in Prometheus exposition format.

    Emits ``# HELP``/``# TYPE`` lines followed by one sample per gauge or
    counter metric, using the index metadata and audit entry counts.

    Args:
        meta: Index metadata dict from ``metadata.get_all()``.
        comps: The shared component registry, used for the audit database.
    """
    print("# HELP code_search_index_status Index health status")
    print("# TYPE code_search_index_status gauge")
    status_map = {"unindexed": 0, "indexing": 1, "ready": 2, "stale": 3, "error": 4}
    status_val = status_map.get(meta.get("index_status", "unindexed"), 0)
    print(f"code_search_index_status{status_val}")
    total_files = meta.get("total_files", "0")
    print("# HELP code_search_files_total Total files indexed")
    print("# TYPE code_search_files_total gauge")
    print(f"code_search_files_total {total_files}")
    total_symbols = meta.get("total_symbols", "0")
    print("# HELP code_search_symbols_total Total symbols indexed")
    print("# TYPE code_search_symbols_total gauge")
    print(f"code_search_symbols_total {total_symbols}")
    total_chunks = meta.get("total_chunks", "0")
    print("# HELP code_search_chunks_total Total code chunks indexed")
    print("# TYPE code_search_chunks_total gauge")
    print(f"code_search_chunks_total {total_chunks}")
    fts_chunks = meta.get("fts_chunks", "0")
    print("# HELP code_search_fts_chunks_total Keyword-indexed chunks (FTS5)")
    print("# TYPE code_search_fts_chunks_total gauge")
    print(f"code_search_fts_chunks_total {fts_chunks}")
    vector_model_available = meta.get("vector_model_available", "false")
    print("# HELP code_search_vector_model_available Whether vector model is available")
    print("# TYPE code_search_vector_model_available gauge")
    print(f"code_search_vector_model_available {'1' if vector_model_available == 'true' else '0'}")
    test_files_included = meta.get("test_files_included", "true")
    print("# HELP code_search_test_files_included Whether test files are included in index")
    print("# TYPE code_search_test_files_included gauge")
    print(f"code_search_test_files_included {'1' if test_files_included == 'true' else '0'}")
    search_modes = meta.get("search_modes_enabled", "ranked")
    print("# HELP code_search_search_modes Enabled search modes (comma-separated)")
    print("# TYPE code_search_search_modes gauge")
    print(f'code_search_search_modes {{modes="{search_modes}"}} 1')
    audit_db: AuditDatabase = comps["audit_db"]
    entries = audit_db.count_entries()
    print("# HELP code_search_audit_entries_total Total audit entries")
    print("# TYPE code_search_audit_entries_total counter")
    print(f"code_search_audit_entries_total {entries}")


def cmd_daemon(args: argparse.Namespace) -> int:
    """Start, stop, or report status of the local unix-socket query daemon."""
    import subprocess
    import sys as _sys

    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    from code_search.engine.daemon import (
        DaemonClient,
        clear_pidfile,
        daemon_status,
        default_socket_path,
    )

    socket_path = Path(args.port) if args.port else default_socket_path(context_dir)

    if args.daemon_action == "status":
        status = daemon_status(context_dir)
        if status["running"]:
            warm = "warm" if status.get("warm") else "warming"
            state = status.get("state") or warm
            print(f"running (pid={status['pid']}, socket={status['socket']}, state={state})")
        else:
            print(f"not running (state={status.get('state') or 'unknown'})")
        return 0

    if args.daemon_action == "wait":
        from code_search.engine.daemon import daemon_status

        deadline = time.monotonic() + float(getattr(args, "timeout", 30.0))
        while time.monotonic() < deadline:
            status = daemon_status(context_dir)
            if status.get("running") and status.get("warm"):
                print("ready")
                return 0
            time.sleep(0.1)
        print("timed out waiting for a warm daemon", file=sys.stderr)
        return 1

    if args.daemon_action == "stop":
        status = daemon_status(context_dir)
        if not status["running"]:
            print("not running")
            return 0
        pid = status.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as exc:
                logger.warning("Failed to signal daemon pid %d: %s", pid, exc)
        with suppress(FileNotFoundError):
            socket_path.unlink()
        clear_pidfile(context_dir)
        print("stopped")
        return 0

    # daemon_action == "start"
    if DaemonClient.is_running(socket_path):
        print(f"already running (socket={socket_path})")
        return 0
    from code_search.engine.daemon import pid_is_alive

    if pid_is_alive(context_dir):
        # A daemon is already spawning; wait for it instead of creating a
        # second process.
        deadline = time.monotonic() + Settings.with_context_dir(context_dir).startup_wait_s
        while time.monotonic() < deadline:
            if DaemonClient.is_serving(socket_path, timeout=0.1):
                print(f"already running (socket={socket_path})")
                return 0
            if not pid_is_alive(context_dir):
                break
            time.sleep(0.05)
        if pid_is_alive(context_dir):
            print("daemon is still starting", file=sys.stderr)
            return 1

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = context_dir / "code-search-daemon.log"
    with log_path.open("a", buffering=1) as log_handle:
        proc = subprocess.Popen(
            [
                _sys.executable,
                "-m",
                "code_search.cli.main",
                "--context-dir",
                str(context_dir),
                "daemon",
                "run",
                "--port",
                str(socket_path),
            ],
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    (context_dir / "code-search.pid").write_text(str(proc.pid))
    print(f"started (pid={proc.pid}, socket={socket_path})")
    return 0


def cmd_daemon_run(args: argparse.Namespace) -> int:
    """Run the daemon in the foreground (used by the backgrounded start)."""
    _setup_logging(args.verbose)
    context_dir = _resolve_context_dir(args)
    from code_search.engine.daemon import default_socket_path, run_daemon_foreground

    socket_path = Path(args.port) if args.port else default_socket_path(context_dir)
    return run_daemon_foreground(context_dir, socket_path, args.verbose)


def _daemon_performance_hint(context_dir: Path) -> str | None:
    """Return a cold-path performance hint when no daemon is running.

    Search was served locally (cold path). Warm the daemon once with
    ``code-search daemon start`` to serve repeat queries from a resident
    process instead of re-initialising the engine per invocation.
    """
    from code_search.engine.daemon import DaemonClient, default_socket_path

    try:
        if DaemonClient.is_running(default_socket_path(context_dir)):
            return None
    except Exception:
        return None
    return (
        "Performance hint: 'code-search daemon start' warms a resident server "
        "and makes repeat searches faster."
    )


def _ensure_resident_service(args: argparse.Namespace) -> bool:
    """Transparently start the resident daemon when none is running.

    A one-shot invocation with no resident service must still meet the
    interactive budget without a manual pre-warm. This spawns the daemon
    fire-and-forget (the existing ``daemon start`` subprocess path) and probes
    readiness with a short timeout. A resident service only owns the model
    load once it answers ``ping``; a daemon that failed to bind must not
    suppress the caller's in-process load.

    Args:
        args: Parsed arguments; the context directory is honoured.

    Returns:
        ``True`` when a (possibly still warming) resident service answered
        ``ping`` and owns the model load; ``False`` when a warm service is
        already available, a stale socket was removed, or the spawned daemon
        never became reachable.
    """
    import subprocess
    import sys as _sys

    from code_search.engine.daemon import (
        DaemonClient,
        default_socket_path,
        pid_is_alive,
    )

    context_dir = _resolve_context_dir(args)
    socket_path = default_socket_path(context_dir)
    serving = socket_path.exists() and DaemonClient.is_serving(socket_path, timeout=0.1)
    if socket_path.exists() and not serving:
        # A starting daemon binds its socket before the model is ready, so a
        # first failed probe is not proof that the socket is stale. When its
        # pidfile names a live process, retry briefly before removing
        # anything; only a dead pid or an expired retry window is treated as
        # a crashed daemon.
        became_ready = False
        if pid_is_alive(context_dir):
            deadline = time.monotonic() + Settings.with_context_dir(context_dir).startup_wait_s
            while time.monotonic() < deadline:
                if DaemonClient.is_serving(socket_path, timeout=0.1):
                    became_ready = True
                    break
                if not pid_is_alive(context_dir):
                    break
                time.sleep(0.05)
            if not became_ready:
                # The recorded process is alive but never became reachable.
                # Do not unlink its state while it may still be initialising;
                # serve this invocation in-process instead.
                return False
        if not became_ready:
            # A stale socket from a crashed/killed daemon must not make every
            # invocation pay a failed connection before falling back. Remove it
            # so the next invocation can start a fresh service cleanly.
            with suppress(OSError):
                socket_path.unlink()
            with suppress(OSError):
                (context_dir / "code-search.pid").unlink()
            return False
        serving = True
    if not socket_path.exists():
        if pid_is_alive(context_dir):
            # Another client already spawned a daemon that has not bound yet.
            # Wait for it instead of creating a competing process.
            deadline = time.monotonic() + Settings.with_context_dir(context_dir).startup_wait_s
            while time.monotonic() < deadline:
                if DaemonClient.is_serving(socket_path, timeout=0.1):
                    return True
                if not pid_is_alive(context_dir):
                    break
                time.sleep(0.05)
            return False
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = context_dir / "code-search-daemon.log"
        with log_path.open("a", buffering=1) as log_handle:
            proc = subprocess.Popen(
                [
                    _sys.executable,
                    "-m",
                    "code_search.cli.main",
                    "--context-dir",
                    str(context_dir),
                    "daemon",
                    "run",
                    "--port",
                    str(socket_path),
                ],
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
        # The daemon writes its own pid; seeding it here closes the window where
        # a second client sees no pid and spawns a duplicate.
        pid = getattr(proc, "pid", os.getpid())
        (context_dir / "code-search.pid").write_text(str(pid))
    # The socket binds before component initialisation, so this window covers
    # process spawn and socket bind only. Never claim the model load without a
    # successful ping: doing so on a dead daemon leaves the one-shot process
    # permanently lexical-only.
    deadline = time.monotonic() + Settings.with_context_dir(context_dir).startup_wait_s
    while True:
        try:
            resp = DaemonClient(socket_path, timeout=0.05).request("ping")
            payload = resp.get("payload") or {}
            if resp.get("ok"):
                return not bool(payload.get("warm"))
        except Exception:
            pass
        if serving:
            # ``is_serving`` already completed a ping on this live listener.
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _try_forward_to_daemon(args: argparse.Namespace) -> int | None:
    """Forward search/symbol/graph to a running daemon; returns exit code or None."""
    from code_search.engine.daemon import DaemonClient, default_socket_path

    context_dir = _resolve_context_dir(args)
    socket_path = default_socket_path(context_dir)
    if not DaemonClient.is_running(socket_path):
        return None
    try:
        client = DaemonClient(socket_path)
        command = args.command
        if command == "search":
            resp = client.request(
                "search",
                {
                    "query": args.query,
                    "limit": args.limit,
                    "language": args.language,
                    "include_tests": args.include_tests,
                    "query_terms": _query_terms(args.query),
                    "mode": getattr(args, "mode", "ranked"),
                    "content": getattr(args, "content", None),
                    "matching": getattr(args, "matching", None),
                    "regex": getattr(args, "regex", False),
                    "allow_weak": bool(getattr(args, "allow_weak", False)),
                    "compact": getattr(args, "compact", True),
                    "max_snippet_lines": getattr(args, "max_snippet_lines", None),
                    "paths_only": getattr(args, "paths_only", False),
                    "startup_wait_s": Settings.with_context_dir(context_dir).startup_wait_s,
                    "wait_for_warm": getattr(args, "wait_for_warm", None) or 0.0,
                },
            )
        elif command == "symbol":
            resp = client.request("symbol", {"fqn": args.fqn})
        elif command == "implementations":
            resp = client.request("implementations", {"fqn": args.fqn})
        elif command == "graph":
            resp = client.request(
                "graph",
                {
                    "fqn": args.fqn,
                    "direction": args.direction,
                    "depth": args.depth,
                    "transitive": args.transitive,
                },
            )
        elif command == "find-related":
            resp = client.request(
                "find_related",
                {"file_path": args.file_path, "line_number": args.line, "limit": args.limit},
            )
        else:
            return None
        if not resp.get("ok"):
            logger.warning("Daemon request failed: %s", resp.get("error"))
            return None
        payload = resp["payload"]
        root = (payload.get("freshness") or {}).get("index_root") or str(context_dir.parent)
        if command == "find-related" and payload.get("results"):
            from code_search.engine.response_service import relativize_results

            payload["results"] = relativize_results(payload["results"], root)
        if args.json:
            indent = (
                2
                if (getattr(args, "pretty", False) or not getattr(args, "compact", True))
                else None
            )
            print(json.dumps(payload, indent=indent, default=str))
        else:
            if command == "search":
                _print_search_results(payload.get("results") or [], root=root)
                _print_match_breakdown(
                    payload.get("production_matches"),
                    payload.get("test_matches"),
                    args.include_tests,
                )
                if payload.get("query_time_ms") is not None:
                    print(f"Query time: {round(float(payload['query_time_ms']))} ms")
                _emit_stale_notice(payload.get("freshness") or {})
                if payload.get("envelope"):
                    print(payload["envelope"], file=sys.stderr)
                _print_scope_override(payload.get("scope") or {})
            elif command == "symbol":
                from code_search.engine.graph_query import display_symbol, relative_display

                if payload.get("symbol"):
                    sym = payload["symbol"]
                    location = relative_display(sym.get("file_path"), root)
                    print(
                        f"{display_symbol(str(sym.get('fqn') or ''))} ({sym.get('kind')}) @ "
                        f"{location}:{sym.get('line_start')}-{sym.get('line_end')}"
                    )
                    print(sym.get("source_code") or "")
                elif payload.get("ambiguous"):
                    _print_ambiguous_candidates(
                        args.fqn, payload.get("candidates") or [], root=root
                    )
                elif payload.get("candidates"):
                    suggestions = [c for c in payload["candidates"] if c.get("suggestion")]
                    if suggestions:
                        best = suggestions[0]
                        print(
                            f"Symbol not found: {args.fqn}. Did you mean: "
                            f"{best.get('name')}? (edit_distance {best.get('edit_distance')})"
                        )
                        for c in suggestions:
                            path = relative_display(c.get("file_path"), root)
                            loc = f"{path}:{c['line_start']}-{c['line_end']}"
                            print(
                                f"  {display_symbol(c['fqn'] or '')} "
                                f"({c['name']}, {c['kind']}) @ {loc}"
                            )
                    else:
                        print(
                            f"Symbol '{args.fqn}' is ambiguous — "
                            f"{len(payload['candidates'])} candidates:"
                        )
                        for c in payload["candidates"][:10]:
                            path = relative_display(c.get("file_path"), root)
                            loc = f"{path}:{c['line_start']}-{c['line_end']}"
                            print(
                                f"  {display_symbol(c['fqn'] or '')} "
                                f"({c['name']}, {c['kind']}) @ {loc}"
                            )
                else:
                    print(f"Symbol not found: {args.fqn}")
                _emit_stale_notice(payload.get("freshness") or {})
            elif command == "graph":
                if args.direction == "implements":
                    _print_implementations(payload, args.fqn, root=root)
                elif payload.get("found"):
                    _print_graph_results(
                        payload["symbol"], payload["callers"], payload["callees"], root=root
                    )
                elif payload.get("ambiguous"):
                    _print_ambiguous_candidates(
                        args.fqn, payload.get("candidates") or [], root=root
                    )
                else:
                    print(f"Symbol not found: {args.fqn}")
                _emit_stale_notice(payload.get("freshness") or {})
            elif command == "implementations":
                _print_implementations(payload, args.fqn, root=root)
                _emit_stale_notice(payload.get("freshness") or {})
        return 0
    except Exception as exc:
        logger.debug("Daemon forwarding failed: %s", exc)
        return None


def cmd_download_models(args: argparse.Namespace) -> int:
    """Download embedding model to Hugging Face cache so it is available offline."""
    from code_search.engine.redactor import allow_downloads

    _setup_logging(args.verbose)
    model_name = args.model or "potion-code-16m-32d"
    print(f"Downloading model '{model_name}'...")
    try:
        from model2vec import StaticModel

        with allow_downloads():
            StaticModel.from_pretrained(model_name)

        print("Verifying model integrity...")
        try:
            model = StaticModel.from_pretrained(model_name)
            test_vec = model.encode("def test(): pass")
            if test_vec is None or len(test_vec) == 0:
                raise ValueError("Model produced empty embeddings after download")
        except Exception as verify_exc:
            logger.warning(
                "Downloaded model '%s' appears corrupted: %s. Cleaning up and retry recommended.",
                model_name,
                verify_exc,
            )
            import shutil

            cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
            if cache_dir.exists():
                for item in cache_dir.iterdir():
                    if model_name.replace("/", "--") in item.name:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
            print(f"Model '{model_name}' download appears incomplete or corrupted.")
            print("Please run 'code-search download-models' again to retry.")
            return 1

        print(f"Model '{model_name}' downloaded and cached successfully.")
        return 0
    except ImportError:
        logger.error("model2vec is not installed. Install it with: pip install code-search[embed]")
        return 1
    except Exception as exc:
        logger.error("Failed to download model '%s': %s", model_name, exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the full ``code-search`` argparse tree.

    Constructs a global ``--context-dir``/``--verbose`` pre-parser plus every
    subcommand (index, search, symbol, graph, metrics, serve, daemon,
    download-models, list-languages), setting each subparser's ``func``.
    Exposed separately so contract tests can introspect the real option
    surface (documentation-drift and surface-parity checks) without running
    the command.

    Returns:
        The configured root parser.
    """
    global_args = argparse.ArgumentParser(add_help=False)
    global_args.add_argument("--context-dir", help="Path to context directory")
    global_args.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    global_args.add_argument(
        "--no-daemon",
        "--no-startup-check",
        dest="no_startup_check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Serve this invocation in-process instead of forwarding to the daemon "
        "(--no-startup-check is a deprecated alias)",
    )

    parser = argparse.ArgumentParser(
        prog="code-search",
        description="An AI code context engine",
        parents=[global_args],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser(
        "index",
        parents=[global_args],
        help="Index a codebase",
        epilog=(
            "CODE_SEARCH_MODEL_PROFILE selects the embedding profile ('default' or "
            "'fast'). Switching profiles changes the persisted vectors, so re-run "
            "'code-search index --force' after switching."
        ),
    )
    index_parser.add_argument("--path", default=".", help="Path to codebase root")
    index_parser.add_argument("--force", action="store_true", help="Force re-index")
    index_parser.add_argument(
        "--runtime-profile",
        choices=["standard", "small", "auto"],
        default=None,
        help="Runtime preset: standard (default), small, or auto",
    )
    index_parser.add_argument(
        "--index-layout",
        choices=["legacy", "compact"],
        default=None,
        help="Persisted index layout (default: derived from the runtime profile)",
    )
    index_parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Build a search-only index without graph edges or symbol rationale",
    )
    index_parser.add_argument("--incremental", action="store_true", help="Incremental index")
    index_parser.add_argument("--watch", action="store_true", help="Watch for changes")
    index_parser.add_argument("--exclude", help="Comma-separated exclusion patterns")
    index_parser.add_argument(
        "--include-tests",
        action="store_true",
        default=True,
        help="Include test files in indexing (default: True)",
    )
    index_parser.add_argument(
        "--no-include-tests",
        action="store_false",
        dest="include_tests",
        help="Exclude test files from indexing",
    )
    index_parser.add_argument(
        "--include-resources",
        "-r",
        action="store_true",
        default=True,
        help="Include resource files (XML, SQL, properties, Gradle, etc.) (default: True)",
    )
    index_parser.add_argument(
        "--exclude-resources",
        action="store_true",
        dest="exclude_resources",
        help="Exclude resource files from indexing",
    )
    index_parser.add_argument(
        "--resource-extensions",
        help="Comma-separated override for resource file extensions",
    )
    index_parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="Prune index rows for files no longer on disk / excluded, then exit",
    )
    index_parser.set_defaults(func=cmd_index)

    search_parser = subparsers.add_parser(
        "search",
        parents=[global_args],
        help="Natural language search",
        epilog=(
            "CODE_SEARCH_MODEL_PROFILE selects the embedding profile ('default' or "
            "'fast'). Switching profiles requires re-running "
            "'code-search index --force' to rebuild vectors for the selected model."
        ),
    )
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--runtime-profile",
        choices=["standard", "small", "auto"],
        default=None,
        help="Runtime preset: standard (default), small, or auto",
    )
    search_parser.add_argument(
        "--search-backend",
        choices=["sqlite", "memory"],
        default=None,
        help="Warm query backend (default: derived from the runtime profile)",
    )
    search_parser.add_argument(
        "--freshness-mode",
        choices=["blocking", "deferred"],
        default=None,
        help="Whether a query waits for the freshness scan (default: blocking)",
    )
    search_parser.add_argument(
        "--wait-for-warm",
        type=float,
        default=None,
        help="Seconds to wait for a cold daemon/model before using the reduced path",
    )
    search_parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Return only location and classification fields (no content)",
    )
    search_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print compact JSON (default is single-line)",
    )
    search_parser.add_argument(
        "--allow-weak",
        action="store_true",
        help="Return the weak ranked pool even when the extra abstention gate fires",
    )
    search_parser.add_argument("--limit", type=int, default=10, help="Max results (max 50)")
    search_parser.add_argument(
        "--content",
        choices=["code", "config", "docs", "all", "code_focused"],
        default=None,
        help="Content-type scope: code, config, docs, all, or code_focused. "
        "Omitting it means no scope preference: a code-shaped query defaults "
        "to code, a documentation-shaped query is widened to all, and other "
        "queries use code_focused (code + config). A configuration-shaped "
        "query under a scope that excludes configuration (code) reports how "
        "to include it. Force a scope with --content all (documentation) or "
        "--content config (configuration).",
    )
    search_parser.add_argument("--language", help="Filter by language")
    search_parser.add_argument(
        "--include-tests",
        action="store_true",
        default=False,
        help="Include test files in search (default: False; tests are demoted, not indexed-out)",
    )
    search_parser.add_argument(
        "--no-include-tests",
        action="store_false",
        dest="include_tests",
        help="Exclude test files from search",
    )
    search_parser.add_argument(
        "--mode",
        choices=["ranked", "exhaustive", "enumerate"],
        default="ranked",
        help="Search mode: ranked (default), exhaustive (line-wise complete match "
        "set for exact-count queries), enumerate (named symbol-kind list)",
    )
    search_parser.add_argument(
        "--matching",
        choices=["literal", "all_tokens", "any_token"],
        default="all_tokens",
        help="Exhaustive matching semantics: literal (verbatim substring), "
        "all_tokens (AND, default), or any_token (OR); applies only in "
        "--mode exhaustive",
    )
    search_parser.add_argument(
        "--regex",
        action="store_true",
        help="Treat the query as a regular expression; requires --mode exhaustive",
    )
    search_parser.add_argument("--json", action="store_true", help="JSON output")
    search_parser.add_argument(
        "--no-model",
        action="store_true",
        help="Fast path: skip vector-model warm-up, fuse lexical only",
    )
    search_parser.add_argument(
        "--explain-ranking",
        action="store_true",
        help="Include the score breakdown for every result and print the ranking components",
    )
    search_parser.add_argument(
        "--compact",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Agent-sized JSON (default): identifiers, locations, signatures, "
        "and a short content snippet instead of full blocks and score "
        "breakdowns; use --no-compact for the full envelope",
    )
    search_parser.add_argument(
        "--max-snippet-lines",
        type=int,
        default=None,
        help="Trim each result to at most N content lines (adds a signature)",
    )
    search_parser.set_defaults(func=cmd_search)

    symbol_parser = subparsers.add_parser(
        "symbol", parents=[global_args], help="Look up symbol by FQN"
    )
    symbol_parser.add_argument("fqn", help="Fully qualified name")
    symbol_parser.add_argument("--json", action="store_true", help="JSON output")
    symbol_parser.set_defaults(func=cmd_symbol)

    graph_parser = subparsers.add_parser("graph", parents=[global_args], help="Traverse call graph")
    graph_parser.add_argument("fqn", help="Fully qualified name")
    graph_parser.add_argument(
        "--direction",
        choices=["both", "callers", "callees", "implements"],
        default="both",
        help="Traversal direction; 'implements' returns static implementations",
    )
    graph_parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Transitive expansion bound used with --transitive (max 5)",
    )
    graph_parser.add_argument(
        "--transitive",
        action="store_true",
        default=False,
        help="Expand transitively to --depth; omit for direct-only",
    )
    graph_parser.add_argument("--json", action="store_true", help="JSON output")
    graph_parser.add_argument(
        "--explain-unresolved",
        action="store_true",
        help="List raw call targets that could not be resolved to indexed symbols",
    )
    graph_parser.set_defaults(func=cmd_graph)

    implementations_parser = subparsers.add_parser(
        "implementations",
        parents=[global_args],
        help="Find static implementations of an interface member or type",
    )
    implementations_parser.add_argument("fqn", help="Interface method or type reference")
    implementations_parser.add_argument("--json", action="store_true", help="JSON output")
    implementations_parser.set_defaults(func=cmd_implementations)

    related_parser = subparsers.add_parser(
        "find-related",
        parents=[global_args],
        help="Find chunks semantically related to a file/line anchor",
    )
    related_parser.add_argument("file_path", help="File path (absolute or project-relative)")
    related_parser.add_argument("--line", type=int, required=True, help="Anchor line number")
    related_parser.add_argument("--limit", type=int, default=5, help="Max related chunks")
    related_parser.add_argument("--json", action="store_true", help="JSON output")
    related_parser.set_defaults(func=cmd_find_related)

    query_parser = subparsers.add_parser(
        "query", parents=[global_args], help="Answer a question by traversing the code graph"
    )
    query_parser.add_argument("question", help="Natural-language or identifier question")
    query_parser.add_argument("--depth", type=int, default=2, help="Traversal depth (max 4)")
    query_parser.add_argument("--max-nodes", type=int, default=120, help="Max graph nodes")
    query_parser.add_argument(
        "--edge-types",
        default="CALLS,INHERITS",
        help="Comma-separated edge types (CALLS, INHERITS, IMPORTS, REFERENCES)",
    )
    query_parser.add_argument(
        "--token-budget", type=int, default=1500, help="Soft output token budget"
    )
    query_parser.add_argument(
        "--include-externals",
        action="store_true",
        help="Include unresolved/external callee leaves (collapsed by default)",
    )
    query_parser.add_argument("--json", action="store_true", help="JSON output")
    query_parser.set_defaults(func=cmd_query)

    path_parser = subparsers.add_parser(
        "path", parents=[global_args], help="Find the shortest graph path between two symbols"
    )
    path_parser.add_argument("source", help="Source symbol reference")
    path_parser.add_argument("target", help="Target symbol reference")
    path_parser.add_argument(
        "--undirected", action="store_true", help="Traverse edges in both directions"
    )
    path_parser.add_argument("--max-hops", type=int, default=6, help="Maximum hops (max 6)")
    path_parser.add_argument(
        "--edge-types",
        default="CALLS,INHERITS",
        help="Comma-separated edge types (CALLS, INHERITS, REFERENCES)",
    )
    path_parser.add_argument("--json", action="store_true", help="JSON output")
    path_parser.set_defaults(func=cmd_path)

    explain_parser = subparsers.add_parser(
        "explain", parents=[global_args], help="Explain a symbol, its relations, and rationale"
    )
    explain_parser.add_argument("symbol", help="Symbol reference")
    explain_parser.add_argument("--depth", type=int, default=1, help="Ego-graph depth (max 4)")
    explain_parser.add_argument(
        "--relations",
        default="CALLS,INHERITS",
        help="Comma-separated relations to include (CALLS, INHERITS, IMPORTS, REFERENCES)",
    )
    explain_parser.add_argument("--json", action="store_true", help="JSON output")
    explain_parser.set_defaults(func=cmd_explain)

    affected_parser = subparsers.add_parser(
        "affected", parents=[global_args], help="Report symbols impacted by changed files"
    )
    affected_parser.add_argument("paths", nargs="*", help="Changed file paths")
    affected_parser.add_argument("--since", help="Git ref to diff against (e.g. HEAD~1)")
    affected_parser.add_argument("--depth", type=int, default=3, help="Reverse depth (max 4)")
    affected_parser.add_argument("--json", action="store_true", help="JSON output")
    affected_parser.set_defaults(func=cmd_affected)

    map_parser = subparsers.add_parser(
        "map", parents=[global_args], help="Generate an architecture report"
    )
    map_parser.add_argument("--output", help="Write the Markdown report to this path")
    map_parser.add_argument("--top", type=int, default=15, help="Number of god nodes")
    map_parser.add_argument(
        "--max-communities", type=int, default=10, help="Maximum communities to report"
    )
    map_parser.add_argument("--json", action="store_true", help="JSON output")
    map_parser.set_defaults(func=cmd_map)

    metrics_parser = subparsers.add_parser("metrics", parents=[global_args], help="Query metrics")
    metrics_parser.add_argument(
        "--format", choices=["human", "json", "prometheus"], default="human"
    )
    metrics_parser.set_defaults(func=cmd_metrics)

    serve_parser = subparsers.add_parser("serve", parents=[global_args], help="Start MCP server")
    serve_parser.set_defaults(func=cmd_serve)

    list_parser = subparsers.add_parser(
        "list-languages", parents=[global_args], help="List supported languages"
    )
    list_parser.set_defaults(func=cmd_list_languages)

    start_parser = subparsers.add_parser(
        "start", parents=[global_args], help="Start the daemon (alias for 'daemon start')"
    )
    start_parser.add_argument("--port", help="Unix socket path")
    start_parser.set_defaults(func=cmd_start)

    status_parser = subparsers.add_parser(
        "status", parents=[global_args], help="Report daemon status (alias for 'daemon status')"
    )
    status_parser.add_argument("--port", help="Unix socket path")
    status_parser.set_defaults(func=cmd_status)

    doctor_parser = subparsers.add_parser(
        "doctor", parents=[global_args], help="Diagnose index, model, and daemon state"
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    stats_parser = subparsers.add_parser(
        "stats", parents=[global_args], help="Show profile, layout, and index footprint"
    )
    stats_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    stats_parser.set_defaults(func=cmd_stats)

    download_parser = subparsers.add_parser(
        "download-models", parents=[global_args], help="Download ML models for offline use"
    )
    download_parser.add_argument(
        "--model", default="", help="Model name to download (default: potion-code-16m-32d)"
    )
    download_parser.set_defaults(func=cmd_download_models)

    daemon_parser = subparsers.add_parser(
        "daemon", parents=[global_args], help="Manage the local query daemon"
    )
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_action", required=True)
    daemon_start = daemon_sub.add_parser("start", parents=[global_args], help="Start the daemon")
    daemon_start.add_argument("--port", help="Unix socket path")
    daemon_stop = daemon_sub.add_parser("stop", parents=[global_args], help="Stop the daemon")
    daemon_stop.add_argument("--port", help="Unix socket path")
    daemon_status_parser = daemon_sub.add_parser(
        "status", parents=[global_args], help="Report daemon status"
    )
    daemon_status_parser.add_argument("--port", help="Unix socket path")
    daemon_wait_parser = daemon_sub.add_parser(
        "wait", parents=[global_args], help="Wait until the daemon is warm"
    )
    daemon_wait_parser.add_argument("--port", help="Unix socket path")
    daemon_wait_parser.add_argument(
        "--timeout", type=float, default=30.0, help="Seconds to wait for a warm daemon"
    )
    daemon_run = daemon_sub.add_parser(
        "run", parents=[global_args], help="Run the daemon in the foreground"
    )
    daemon_run.add_argument("--port", help="Unix socket path")
    daemon_run.set_defaults(func=cmd_daemon_run)
    daemon_parser.set_defaults(func=cmd_daemon)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the selected subcommand handler.

    Builds the argparse tree via :func:`build_parser`, then executes the
    chosen handler inside an air-gap enforcement context, exiting with the
    handler's exit code (or ``1`` on an unexpected exception).
    """
    parser = build_parser()
    args = parser.parse_args()
    try:
        from code_search.engine.redactor import air_gap_enforcement

        with air_gap_enforcement():
            sys.exit(args.func(args))
    except Exception as exc:
        logger.error("Command failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
