"""Index orchestrator — coordinates full and incremental codebase indexing.

Walks discovered source files, extracts symbols + edges via AST, chunks code,
generates embeddings, and persists everything to the graph database and vector index.
"""

from __future__ import annotations

import hashlib
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.engine.classification import content_type as classify_content_type
from src.engine.config import Settings, _is_test_file
from src.engine.embed_representation import (
    REPRESENTATION_SCHEME_VERSION,
    build_embed_text,
    derive_enclosing_context,
)
from src.engine.embeddings import (
    EmbeddingGenerator,
    VectorIndex,
    get_representation_scheme_version,
    set_representation_scheme_version,
)
from src.engine.graph import SCHEMA_VERSION, EdgeStore, GraphDatabase, IndexMetadataStore
from src.engine.parser import ASTParser
from src.engine.search import identify_subwords
from src.engine.symbols import SymbolExtractor, SymbolStore

logger = logging.getLogger(__name__)

# Use the "spawn" start method for the indexer's process pools. Forking a
# process that already holds threads (numpy, the embedding model, etc.) can
# degrade throughput or deadlock under load. Spawn keeps worker start-up
# deterministic.
_POOL_CTX = multiprocessing.get_context("spawn")

# Process pools only pay off above a minimum batch size: every worker pays a
# spawn-time module re-import that multiplies startup cost and memory
# footprint. Below that, running in-process is faster and avoids pathologically
# slow indexing on memory-constrained machines.
_PARSE_MIN_BATCH_PER_WORKER = 50

# Symbol kinds that declare a type. Used when resolving an inheritance base
# that an import map expanded to a dotted module path (for example a Python
# ``from pkg.animal import Animal`` -> ``pkg.animal.Animal``): the base names a
# type, never a receiver-qualified ``Class.method``, so the resolver may fall
# back to the unique type declaration sharing its leaf name.
_TYPE_DECLARATION_KINDS = {"class", "interface", "enum", "type_alias"}


def _process_file_worker(args: tuple[Path, bytes, str, tuple[str, ...] | None]) -> dict[str, Any]:
    """Standalone pickle-safe worker for parallel AST parsing.

    Accepts ``(file_path, source_bytes, language, resource_extensions)``
    and returns a serialisable dict with symbols, edges, chunks, and metadata.
    """
    file_path, source_bytes, language, resource_extensions = args
    from src.engine.parser import ASTParser
    from src.engine.symbols import SymbolExtractor

    parser = ASTParser()
    extractor = SymbolExtractor(parser)

    is_resource = language in {"xml", "sql", "properties", "gradle", "dockerfile", "makefile"}
    syms = extractor.extract_symbols(file_path, source_bytes)
    edges = extractor.extract_edges(file_path, source_bytes)
    chunks = parser.get_chunks_for_file(file_path, source_bytes)
    parse_failed = False
    if not chunks:
        if is_resource or language in {"unknown"}:
            chunks = _fallback_chunk_file(file_path, source_bytes, language, 100)
        else:
            chunks = _module_fallback_chunk(file_path, source_bytes, language)
            parse_failed = file_path.suffix.lower() not in (resource_extensions or ())
    for chunk in chunks:
        if is_resource:
            chunk["chunk_type"] = "resource"
            chunk["chunk_node_type"] = "raw_text"
        chunk["content_type"] = classify_content_type(file_path).value
        chunk["fqn"] = _resolve_chunk_fqn(chunk, syms)
        chunk["embed_context"] = derive_enclosing_context(chunk, syms)
    content_hash = hashlib.sha256(source_bytes).hexdigest()

    return {
        "file_path": str(file_path),
        "symbols": syms,
        "edges": edges,
        "chunks": chunks,
        "content_hash": content_hash,
        "parse_failed": parse_failed,
    }


def _resolve_chunk_fqn(chunk: dict[str, Any], symbols: list[dict[str, Any]]) -> str:
    """Stamp a chunk with the FQN of the symbol it defines.

    A chunk is attributed to the most specific enclosing symbol whose
    declaration line range contains the chunk's start line — a definition
    chunk therefore inherits the FQN of the definition it represents, while
    reference/comment chunks inherit their smallest enclosing symbol. Falls
    back to a file-scoped ``{file_path}::{first_line}`` hint when no symbol
    contains the chunk.
    """
    file_path = chunk.get("file_path", "")
    if not symbols:
        content = chunk.get("content", "")
        name_hint = content.strip().split("\n")[0][:40] if content else "unknown"
        return f"{file_path}::{name_hint}"
    chunk_start = chunk.get("line_start")
    if chunk_start is None:
        return str(symbols[0].get("fqn", ""))
    best: dict[str, Any] | None = None
    best_span: int | None = None
    for sym in symbols:
        s = sym.get("line_start")
        e = sym.get("line_end")
        if s is None or e is None or chunk_start < s or chunk_start > e:
            continue
        span = e - s
        if best is None or span < best_span:
            best = sym
            best_span = span
    if best is not None:
        return str(best.get("fqn", ""))
    content = chunk.get("content", "")
    name_hint = content.strip().split("\n")[0][:40] if content else "unknown"
    return f"{file_path}::{name_hint}"


class IndexLock:
    """Filesystem-based exclusive lock to prevent concurrent indexing.

    Uses ``O_CREAT | O_EXCL`` for atomic acquisition and falls back to
    stale-lock detection + forced release after *timeout* seconds.
    """

    def __init__(self, lock_path: Path, timeout: float = 30.0) -> None:
        """Initialize a filesystem lock rooted at *lock_path*.

        Args:
            lock_path: The lock-file path to create on acquisition.
            timeout: Seconds before a lock is considered stale and force-
                releasable (default 30.0).
        """
        self._lock_path = lock_path
        self._timeout = timeout
        self._acquired = False

    def try_acquire(self) -> bool:
        """Attempt one atomic lock acquisition without waiting.

        Returns:
            ``True`` when the lock was created by this process, ``False`` when
            another process holds it or creation failed.
        """
        try:
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(time.time()))
            self._acquired = True
            logger.debug("Index lock acquired at %s", self._lock_path)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            logger.warning("Failed to acquire index lock: %s", exc)
            return False

    def acquire(self) -> bool:
        """Poll for the lock until timeout or stale detection triggers a force release."""
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self.try_acquire():
                return True
            if self._is_stale():
                self.release(force=True)
                if self.try_acquire():
                    return True
            time.sleep(0.5)
        return False

    def _is_stale(self) -> bool:
        """Return whether the lock file is old enough to be considered abandoned."""
        try:
            mtime = self._lock_path.stat().st_mtime
            return (time.time() - mtime) > self._timeout
        except FileNotFoundError:
            return False

    def release(self, force: bool = False) -> None:
        """Release the lock by deleting its file.

        Args:
            force: Release even when this process did not acquire the lock
                (used to clear stale locks).
        """
        if not self._acquired and not force:
            return
        try:
            self._lock_path.unlink()
            self._acquired = False
            logger.debug("Index lock released at %s", self._lock_path)
        except FileNotFoundError:
            self._acquired = False
        except OSError as exc:
            logger.warning("Failed to release index lock: %s", exc)

    def __enter__(self) -> IndexLock:
        """Acquire the lock and return self for use as a context manager.

        Raises:
            RuntimeError: When the lock cannot be acquired within the
                configured timeout.
        """
        if not self.acquire():
            raise RuntimeError(
                f"Could not acquire index lock at {self._lock_path} "
                f"within {self._timeout}s timeout. "
                "Another indexing operation may be in progress."
            )
        return self

    def __exit__(self, *args: object) -> None:
        """Release the lock when leaving the ``with`` block."""
        self.release()

    @property
    def is_locked(self) -> bool:
        """Return whether the lock file currently exists on disk."""
        return self._lock_path.exists()

    @property
    def acquired(self) -> bool:
        """Return whether this process currently holds the lock."""
        return self._acquired


def _module_fallback_chunk(
    file_path: Path, source_bytes: bytes, language: str, max_chunk_lines: int = 100
) -> list[dict[str, Any]]:
    """Structural-chunk guarantee for source files with no recognized AST node.

    Indexes the file's top-level block as a single ``ast``/``module`` chunk so
    code files are never silently demoted to ``raw_text`` chunks (which hide
    them from structural queries and pollute the raw-text pool with code).
    Oversized files are subdivided into line blocks while preserving the
    ``module`` node type.
    """
    text = source_bytes.decode("utf-8", errors="replace")
    lines = text.split("\n")
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(lines), max_chunk_lines):
        block = lines[i : i + max_chunk_lines]
        block_text = "\n".join(block)
        if not block_text.strip():
            continue
        chunks.append(
            {
                "file_path": str(file_path),
                "line_start": i,
                "line_end": i + len(block) - 1,
                "content": block_text,
                "language": language,
                "is_definition": False,
                "chunk_type": "ast",
                "chunk_node_type": "module",
            }
        )
    return chunks


def _fallback_chunk_file(
    file_path: Path, source_bytes: bytes, language: str, max_chunk_lines: int = 100
) -> list[dict[str, Any]]:
    """Line-based chunker used when AST parsing yields no results.

    Emits a SINGLE chunk per file: the whole file becomes one chunk so a SQL
    migration that previously split into many blank-line blocks now contributes
    exactly one deduped result. Files larger than
    *max_chunk_lines* are still subdivided so embeddings stay within budget.
    """
    text = source_bytes.decode("utf-8", errors="replace")
    lines = text.split("\n")
    chunks: list[dict[str, Any]] = []
    block_start = 0
    block_lines: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "":
            if len(block_lines) >= 2:
                chunk_text = "\n".join(block_lines)
                if chunk_text.strip():
                    chunks.append(
                        {
                            "file_path": str(file_path),
                            "line_start": block_start,
                            "line_end": block_start + len(block_lines) - 1,
                            "content": chunk_text,
                            "language": language,
                            "is_definition": False,
                            "chunk_type": "raw_text",
                            "chunk_node_type": "raw_text",
                        }
                    )
            block_start = i + 1
            block_lines = []
        else:
            block_lines.append(line)
    if len(block_lines) >= 2:
        chunk_text = "\n".join(block_lines)
        if chunk_text.strip():
            chunks.append(
                {
                    "file_path": str(file_path),
                    "line_start": block_start,
                    "line_end": block_start + len(block_lines) - 1,
                    "content": chunk_text,
                    "language": language,
                    "is_definition": False,
                    "chunk_type": "raw_text",
                    "chunk_node_type": "raw_text",
                }
            )

    # Single-chunk-per-file guarantee: merge the blank-line blocks into one
    # chunk covering the whole file, unless the file is oversized and must be
    # subdivided for embedding budget.
    total_lines = len(lines)
    if not chunks and text.strip():
        return [
            {
                "file_path": str(file_path),
                "line_start": 0,
                "line_end": total_lines - 1,
                "content": text.rstrip("\n"),
                "language": language,
                "is_definition": False,
                "chunk_type": "raw_text",
                "chunk_node_type": "raw_text",
            }
        ]

    if len(chunks) > 1 and total_lines <= max_chunk_lines:
        merged_content = "\n".join(text.rstrip("\n").split("\n"))
        return [
            {
                "file_path": str(file_path),
                "line_start": 0,
                "line_end": total_lines - 1,
                "content": merged_content,
                "language": language,
                "is_definition": False,
                "chunk_type": "raw_text",
                "chunk_node_type": "raw_text",
            }
        ]

    merged: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk["line_end"] - chunk["line_start"] > max_chunk_lines:
            chunk_lines = chunk["content"].split("\n")
            for i in range(0, len(chunk_lines), max_chunk_lines):
                block = chunk_lines[i : i + max_chunk_lines]
                merged.append(
                    {
                        "file_path": chunk["file_path"],
                        "line_start": chunk["line_start"] + i,
                        "line_end": chunk["line_start"] + i + len(block) - 1,
                        "content": "\n".join(block),
                        "language": chunk["language"],
                        "is_definition": False,
                        "chunk_type": "raw_text",
                        "chunk_node_type": "raw_text",
                    }
                )
        else:
            merged.append(chunk)
    return merged


class IndexOrchestrator:
    """Top-level coordinator for indexing a codebase.

    Orchestrates file discovery, symbol extraction, edge detection, chunking,
    embedding generation, and persistence across the graph DB and vector index.
    """

    def __init__(
        self,
        db: GraphDatabase,
        metadata_store: IndexMetadataStore,
        parser: ASTParser,
        symbol_extractor: SymbolExtractor,
        symbol_store: SymbolStore,
        embedding_generator: EmbeddingGenerator,
        vector_index: VectorIndex,
        context_dir: Path,
        settings: Settings | None = None,
        edge_store: EdgeStore | None = None,
        freshness: Any | None = None,
    ) -> None:
        """Initialize the orchestrator with all pipeline dependencies.

        Args:
            db: The graph database persisting symbols, edges, and chunks.
            metadata_store: Key-value store recording index lifecycle state.
            parser: Source-file discovery and AST parsing.
            symbol_extractor: AST → symbol/edge extraction.
            symbol_store: Symbol persistence.
            embedding_generator: Vector embedding generation.
            vector_index: Flat-file vector store.
            context_dir: Directory holding the index lock and sidecar files.
            settings: Engine settings; defaults to ``Settings.from_env()``.
            edge_store: Edge persistence; defaults to a fresh ``EdgeStore``
                over *db*.
            freshness: Optional freshness tracker to mark clean post-index.
        """
        self._db = db
        self._metadata = metadata_store
        self._edge_store = edge_store or EdgeStore(db)
        self._parser = parser
        self._symbol_extractor = symbol_extractor
        self._symbol_store = symbol_store
        self._embedding_generator = embedding_generator
        self._vector_index = vector_index
        self._context_dir = context_dir
        self._settings = settings or Settings.from_env()
        self._freshness = freshness

    def index_codebase(
        self,
        root_path: Path,
        force: bool = False,
        incremental: bool = False,
        verbose: bool = False,
        exclusion_patterns: set[str] | None = None,
        include_tests: bool = True,
        include_resources: bool = False,
        resource_extensions: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Run a full or incremental index over *root_path*.

        The pipeline runs in four phases: (1) serial file discovery and
        content-hash diffing, (2) parallel AST parsing/worker dispatch,
        (3) serial symbol/edge/chunk persistence plus cross-file edge
        resolution, and (4) parallel embedding generation. Afterwards it runs
        the stale-file sweep, FTS rebuild, and edge-validation sweep, then
        records summary metadata.

        Args:
            root_path: The repository root to index.
            force: Bypass an in-progress lock and force re-index.
            incremental: Only reprocess changed files (diffed by content
                checksum) and prune orphaned entries.
            verbose: Log per-file progress details.
            exclusion_patterns: Extra directory names to skip during
                discovery, layered over the parser defaults.
            include_tests: Whether test files are indexed.
            include_resources: Whether resource files matching
                *resource_extensions* are indexed.
            resource_extensions: Extension allowlist for resource files.

        Returns:
            A summary dict ``{total_files, total_symbols, total_chunks,
            languages, duration_s}``.

        Raises:
            RuntimeError: When indexing is already in progress and *force* is
                not set.
        """
        lock_path = self._context_dir / "index.lock"
        lock = IndexLock(lock_path, timeout=self._settings.lock_timeout)
        if lock.is_locked and not force:
            raise RuntimeError("Indexing already in progress")

        with lock:
            schema_version = self._metadata.get_int("index_version")
            index_status = self._metadata.get_index_status()
            if index_status == "stale" or (
                schema_version is not None and schema_version < SCHEMA_VERSION
            ):
                force = True
                incremental = False
                logger.info(
                    "Index version %s (status %s) requires re-index. Forcing full re-index.",
                    schema_version,
                    index_status,
                )
            stored_scheme = get_representation_scheme_version(self._metadata)
            engine_built = bool(self._metadata.get("vector_model_name"))
            scheme_stale = (
                stored_scheme is not None and stored_scheme != REPRESENTATION_SCHEME_VERSION
            ) or (stored_scheme is None and self._vector_index.size > 0 and engine_built)
            if scheme_stale:
                force = True
                incremental = False
                logger.info(
                    "Representation scheme %s (stored) != %s (active). Forcing full re-index.",
                    stored_scheme,
                    REPRESENTATION_SCHEME_VERSION,
                )
            model_available = self._embedding_generator.is_available()
            if not model_available:
                from src.engine.embeddings import _emit_warning_once

                _emit_warning_once(
                    f"model:{self._settings.embedding_model}",
                    "Vector model %s not available. Indexing will proceed with BM25-only.",
                    self._settings.embedding_model,
                )
            self._metadata.set("vector_model_loaded", str(model_available).lower())
            self._metadata.set_index_status("indexing")
            start_time = time.monotonic()

            # Phase 1 (serial): File discovery and content-hash diffing
            res_exts = resource_extensions if include_resources else None
            all_files = self._parser.discover_files(
                root_path,
                exclusion_patterns,
                include_resources=include_resources,
                resource_extensions=res_exts,
                index_prose=self._settings.index_prose,
            )
            if not include_tests:
                all_files = [f for f in all_files if not _is_test_file(f)]

            if not incremental:
                self._vector_index.clear()
                with self._db.write_transaction() as conn:
                    conn.execute("DELETE FROM graph_edges;")
                    conn.execute("DELETE FROM symbols;")
                    conn.execute("DELETE FROM code_chunks;")
                    conn.execute("DELETE FROM chunks_fts;")
                    conn.execute("DELETE FROM file_checksums;")

            files_to_process: list[Path] = list(all_files)
            orphaned_paths: list[str] = []

            if incremental:
                existing_checksums: dict[str, str] = {}
                baselines: dict[str, dict[str, Any]] = {}
                with self._db.connect() as conn:
                    rows = conn.execute(
                        "SELECT file_path, checksum, size, file_mtime_ns FROM file_checksums;"
                    ).fetchall()
                    for row in rows:
                        existing_checksums[row["file_path"]] = row["checksum"]
                        baselines[row["file_path"]] = dict(row)

                files_to_process = []
                for fp in all_files:
                    fp_str = str(fp)
                    stored_hash = existing_checksums.pop(fp_str, None)
                    baseline = baselines.get(fp_str)
                    if (
                        stored_hash is not None
                        and baseline is not None
                        and baseline["checksum"] == stored_hash
                    ):
                        st = self._file_stat(fp)
                        if (
                            st is not None
                            and baseline["size"] is not None
                            and baseline["file_mtime_ns"] is not None
                            and st.st_size == baseline["size"]
                            and st.st_mtime_ns == baseline["file_mtime_ns"]
                        ):
                            if verbose:
                                logger.info("Skipping unchanged (stat): %s", fp)
                            continue
                    try:
                        current_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
                    except Exception:
                        continue
                    if stored_hash != current_hash:
                        files_to_process.append(fp)
                    elif verbose:
                        logger.info("Skipping unchanged: %s", fp)

                orphaned_paths = list(existing_checksums.keys())
                for orphan in orphaned_paths:
                    if verbose:
                        logger.info("Removing orphaned: %s", orphan)
                    with self._db.write_transaction() as conn:
                        orphan_chunks = conn.execute(
                            "SELECT id FROM code_chunks WHERE file_path = ?;", (orphan,)
                        ).fetchall()
                        self._vector_index.remove_many([r["id"] for r in orphan_chunks])
                        conn.execute("DELETE FROM code_chunks WHERE file_path = ?;", (orphan,))
                        conn.execute("DELETE FROM chunks_fts WHERE file_path = ?;", (orphan,))
                        orphan_syms = conn.execute(
                            "SELECT id FROM symbols WHERE file_path = ?;", (orphan,)
                        ).fetchall()
                        orphan_sym_ids = [r["id"] for r in orphan_syms]
                        if orphan_sym_ids:
                            ph = ",".join("?" for _ in orphan_sym_ids)
                            conn.execute(
                                f"DELETE FROM graph_edges "
                                f"WHERE source_symbol_id IN ({ph}) "
                                f"OR target_symbol_id IN ({ph});",
                                orphan_sym_ids + orphan_sym_ids,
                            )
                        conn.execute("DELETE FROM symbols WHERE file_path = ?;", (orphan,))
                        conn.execute("DELETE FROM file_checksums WHERE file_path = ?;", (orphan,))

            total = len(files_to_process)
            if total == 0 and not orphaned_paths:
                self._vector_index.save()
                fts_count = self._ensure_fts_parity()
                self._metadata.set_fts_chunks(fts_count)
                self._metadata.set_index_status("ready")
                return {
                    "total_files": 0,
                    "total_symbols": 0,
                    "total_chunks": 0,
                    "languages": [],
                    "duration_s": 0.0,
                }

            # Remove stale entries for modified files before dispatching to workers
            if incremental:
                for fp in files_to_process:
                    fp_str = str(fp)
                    with self._db.write_transaction() as conn:
                        old_chunks = conn.execute(
                            "SELECT id FROM code_chunks WHERE file_path = ?;", (fp_str,)
                        ).fetchall()
                        self._vector_index.remove_many([r["id"] for r in old_chunks])
                        conn.execute("DELETE FROM code_chunks WHERE file_path = ?;", (fp_str,))
                        conn.execute("DELETE FROM chunks_fts WHERE file_path = ?;", (fp_str,))
                        old_symbols = conn.execute(
                            "SELECT id FROM symbols WHERE file_path = ?;", (fp_str,)
                        ).fetchall()
                        old_sym_ids = [r["id"] for r in old_symbols]
                        if old_sym_ids:
                            ph = ",".join("?" for _ in old_sym_ids)
                            conn.execute(
                                f"DELETE FROM graph_edges "
                                f"WHERE source_symbol_id IN ({ph}) "
                                f"OR target_symbol_id IN ({ph});",
                                old_sym_ids + old_sym_ids,
                            )
                        conn.execute("DELETE FROM symbols WHERE file_path = ?;", (fp_str,))

            # Phase 2 (parallel): AST parsing via ProcessPoolExecutor
            worker_args: list[tuple[Path, bytes, str, tuple[str, ...] | None]] = []
            for fp in files_to_process:
                try:
                    source_bytes = fp.read_bytes()
                except Exception:
                    continue
                lang = self._parser.detect_language(fp, resource_extensions=res_exts) or "unknown"
                worker_args.append((fp, source_bytes, lang, res_exts))

            processed_results: list[dict[str, Any]] = []
            if worker_args:
                num_workers = min(os.cpu_count() or 4, len(worker_args))
                if (
                    num_workers > 1
                    and len(worker_args) >= num_workers * _PARSE_MIN_BATCH_PER_WORKER
                ):
                    with ProcessPoolExecutor(
                        mp_context=_POOL_CTX, max_workers=num_workers
                    ) as executor:
                        processed_results = list(executor.map(_process_file_worker, worker_args))
                else:
                    for args in worker_args:
                        processed_results.append(_process_file_worker(args))

            # Phase 3 (serial): DB writes
            total_symbols = 0
            total_chunks = 0
            languages: set[str] = set()
            unresolved_edges: list[dict[str, Any]] = []
            has_resource_files = False

            for result in processed_results:
                file_path_str = result["file_path"]
                syms = result["symbols"]
                edges = result["edges"]
                chunks = result["chunks"]
                content_hash = result["content_hash"]

                if verbose:
                    logger.info(
                        "Processing: %s (%d syms, %d chunks)",
                        file_path_str,
                        len(syms),
                        len(chunks),
                    )

                existing_fqns: set[str] = set()
                for sym in syms:
                    fqn = sym.get("fqn", "")
                    if fqn in existing_fqns:
                        logger.warning("FQN collision detected: %s in %s", fqn, file_path_str)
                    existing_fqns.add(fqn)

                id_map = self._symbol_store.insert_symbols_batch(syms)
                total_symbols += len(id_map)
                if syms:
                    languages.add(syms[0].get("language", "unknown"))

                resolved_edges = []
                for edge in edges:
                    src_id = id_map.get(edge["source_fqn"])
                    tgt_fqn = edge["target_fqn"]
                    tgt_id = id_map.get(tgt_fqn)
                    if tgt_id is None and "::" not in tgt_fqn and file_path_str:
                        tgt_id = id_map.get(f"{file_path_str}::{tgt_fqn}")
                    if src_id is not None and tgt_id is not None:
                        resolved_edges.append(
                            {
                                "source_symbol_id": src_id,
                                "target_symbol_id": tgt_id,
                                "edge_type": edge["edge_type"],
                                "source_range": edge.get("source_range"),
                                "target_range": edge.get("target_range"),
                                "resolution_tier": "exact",
                            }
                        )
                    else:
                        unresolved_edges.append(edge)
                if resolved_edges:
                    self._edge_store.insert_edges_batch(resolved_edges)

                for chunk in chunks:
                    chunk_id = self._insert_chunk(chunk, b"")
                    if chunk_id is not None:
                        total_chunks += 1
                        chunk["_chunk_id"] = chunk_id
                        if chunk.get("chunk_type") == "resource":
                            has_resource_files = True

                with self._db.write_transaction() as conn:
                    try:
                        st = Path(file_path_str).stat()
                        size = st.st_size
                        file_mtime_ns = st.st_mtime_ns
                    except OSError:
                        size = None
                        file_mtime_ns = None
                    conn.execute(
                        "INSERT OR REPLACE INTO file_checksums "
                        "(file_path, checksum, size, file_mtime_ns, parse_failed) "
                        "VALUES (?, ?, ?, ?, ?);",
                        (
                            file_path_str,
                            content_hash,
                            size,
                            file_mtime_ns,
                            1 if result.get("parse_failed") else 0,
                        ),
                    )

            # Cross-file edge resolution: batch-resolve unresolved edges against persisted symbols
            if unresolved_edges:
                source_fqns = list(
                    {e.get("source_fqn", "") for e in unresolved_edges if e.get("source_fqn")}
                )
                target_fqns = list(
                    {e.get("target_fqn", "") for e in unresolved_edges if e.get("target_fqn")}
                )
                with self._db.connect() as conn:
                    src_ids: dict[str, int] = {}
                    if source_fqns:
                        placeholders = ",".join("?" for _ in source_fqns)
                        src_rows = conn.execute(
                            f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
                            source_fqns,
                        ).fetchall()
                        src_ids = {r["fqn"]: r["id"] for r in src_rows}
                    tgt_ids: dict[str, int] = {}
                    if target_fqns:
                        placeholders = ",".join("?" for _ in target_fqns)
                        tgt_rows = conn.execute(
                            f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
                            target_fqns,
                        ).fetchall()
                        tgt_ids = {r["fqn"]: r["id"] for r in tgt_rows}
                    batch_edges: list[dict[str, Any]] = []
                    for edge in unresolved_edges:
                        edge_src_id: int | None = src_ids.get(edge.get("source_fqn", ""))
                        src_tier: str | None = "exact"
                        if edge_src_id is None:
                            edge_src_id, src_tier = self._resolve_cross_file_symbol(
                                conn,
                                edge.get("source_fqn", ""),
                                source_range=edge.get("source_range"),
                            )
                        if edge_src_id is None:
                            continue
                        edge_tgt_id: int | None = tgt_ids.get(edge.get("target_fqn", ""))
                        tgt_tier: str | None = "exact"
                        if edge_tgt_id is None:
                            edge_tgt_id, tgt_tier = self._resolve_cross_file_symbol(
                                conn,
                                edge.get("target_fqn", ""),
                                edge.get("source_fqn", ""),
                                edge.get("source_range"),
                                type_only=edge.get("edge_type") == "INHERITS",
                            )
                        if edge_tgt_id is None:
                            if not self._settings.capture_unresolved_callees:
                                continue
                            # Persist the unresolved/external callee
                            # reference as a ``resolved: 0`` edge carrying the
                            # raw callee text instead of dropping it, so
                            # framework/external calls and typos surface in the
                            # call graph (distinguishable by ``target_raw``).
                            batch_edges.append(
                                {
                                    "source_symbol_id": edge_src_id,
                                    "target_symbol_id": None,
                                    "edge_type": edge["edge_type"],
                                    "source_range": edge.get("source_range"),
                                    "target_range": edge.get("target_range"),
                                    "resolved": 0,
                                    "target_raw": edge.get("target_raw")
                                    or edge.get("target_fqn", ""),
                                }
                            )
                            continue
                        tier = src_tier if src_tier != "exact" else tgt_tier
                        edge_dict: dict[str, Any] = {
                            "source_symbol_id": edge_src_id,
                            "target_symbol_id": edge_tgt_id,
                            "edge_type": edge["edge_type"],
                            "source_range": edge.get("source_range"),
                            "target_range": edge.get("target_range"),
                            "resolution_tier": tier,
                        }
                        if edge_src_id == edge_tgt_id:
                            call_line = self._declaration_line_from_range(edge.get("source_range"))
                            recursive = self._call_is_recursive(conn, edge_src_id, call_line)
                            if not recursive:
                                continue
                            edge_dict["recursive"] = True
                        batch_edges.append(edge_dict)
                    if batch_edges:
                        self._edge_store.insert_edges_batch(batch_edges)

            # Phase 4 (serial): Batch embedding generation in-process.
            # The parse phase stays process-pooled (CPU-bound); embedding moves
            # to one batched ``model.encode`` call per batch via encode_batch.
            embed_args: list[tuple[str, int, str, str, str]] = []
            if self._embedding_generator.is_available():
                budget = self._settings.embed_text_max_chars
                for result in processed_results:
                    for chunk in result["chunks"]:
                        chunk_id = chunk.get("_chunk_id")
                        if chunk_id is not None:
                            embed_args.append(
                                (
                                    build_embed_text(
                                        chunk.get("embed_context"),
                                        chunk.get("content", ""),
                                        budget,
                                    ),
                                    chunk_id,
                                    chunk.get("file_path", ""),
                                    chunk.get("fqn", ""),
                                    chunk.get("content_type") or "code",
                                )
                            )

            if embed_args:
                embed_texts = [text for text, _, _, _, _ in embed_args]
                embed_vectors = self._embedding_generator.encode_batch(embed_texts)
                for (_, chunk_id, file_path, fqn, content_type), embedding in zip(
                    embed_args, embed_vectors, strict=True
                ):
                    if embedding is not None:
                        self._vector_index.add(
                            chunk_id,
                            embedding,
                            {"file_path": file_path, "fqn": fqn, "content_type": content_type},
                        )

            self._vector_index.save()
            duration_s = time.monotonic() - start_time

            # Post-index stale sweep: a full re-index already covers the whole
            # tree, and incremental diffing removes working-tree orphans, so
            # the sweep only re-runs when the indexing policy changed (files
            # may have become excluded).
            if not incremental or self._indexing_policy_changed(
                root_path, include_tests, include_resources, res_exts, exclusion_patterns
            ):
                self._sweep_stale_files(root_path)

            # Keep the keyword index in parity with code_chunks. Full indexes
            # rebuild unconditionally; incremental ones only rebuild when the
            # FTS maintenance triggers have drifted.
            fts_count = self._ensure_fts_parity(force=not incremental)
            self._metadata.set_fts_chunks(fts_count)

            # Post-index edge validation sweep: remove spurious self-edges,
            # same-name mis-resolutions, and out-of-range
            # attachments while preserving genuine recursive self-calls.
            try:
                self._edge_store.run_edge_validation_sweep()
            except Exception as exc:
                logger.warning("Edge validation sweep failed: %s", exc)

            self._metadata.set(
                "last_indexed_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            )
            self._metadata.set_int("total_files", total)
            self._metadata.set_int("total_symbols", total_symbols)
            self._metadata.set_int("total_chunks", total_chunks)
            self._metadata.set_json("languages", sorted(languages))
            self._metadata.set(
                "vector_model_available", str(self._embedding_generator.is_available()).lower()
            )
            self._metadata.set("vector_model_name", self._settings.embedding_model)
            set_representation_scheme_version(self._metadata)
            self._metadata.set_json("supported_languages", sorted(languages))
            self._metadata.set("test_files_included", str(include_tests).lower())
            if include_resources:
                self._metadata.set_json("resource_extensions", list(res_exts) if res_exts else [])
                self._metadata.set("has_resource_files", str(has_resource_files).lower())
            self._metadata.set("index_root", str(root_path.resolve()))
            self._metadata.set("index_include_tests", str(include_tests).lower())
            self._metadata.set("index_include_resources", str(include_resources).lower())
            self._metadata.set_json("index_resource_extensions", list(res_exts) if res_exts else [])
            self._metadata.set_json(
                "index_exclusion_patterns", sorted(exclusion_patterns) if exclusion_patterns else []
            )
            self._metadata.set("index_prose", str(self._settings.index_prose).lower())
            self._metadata.set_index_status("ready")
            self._metadata.set(
                "search_modes_enabled",
                ",".join(
                    mode
                    for mode, flag in (
                        ("ranked", True),
                        ("exhaustive", self._settings.exhaustive_enabled),
                        ("enumerate", self._settings.enumerate_enabled),
                    )
                    if flag
                ),
            )

            if self._freshness is not None:
                try:
                    self._freshness.mark_clean()
                except Exception:
                    logger.warning("Freshness mark_clean after index failed", exc_info=True)

            return {
                "total_files": total,
                "total_symbols": total_symbols,
                "total_chunks": total_chunks,
                "languages": sorted(languages),
                "duration_s": round(duration_s, 1),
            }

    @staticmethod
    def _file_stat(path: Path) -> os.stat_result | None:
        """Return the stat result for *path*, or ``None`` when it is missing."""
        try:
            return path.stat()
        except OSError:
            return None

    def _ensure_fts_parity(self, force: bool = False) -> int:
        """Return the FTS row count, rebuilding only when it drifted.

        Full indexes pass *force* so the keyword index is rebuilt up front;
        incremental indexes rely on the FTS maintenance triggers and rebuild
        only when ``COUNT(chunks_fts) != COUNT(code_chunks)``.

        Args:
            force: Rebuild unconditionally instead of comparing row counts.

        Returns:
            The number of rows in ``chunks_fts`` afterwards.
        """
        if force:
            return self._db.rebuild_fts()
        with self._db.connect() as conn:
            code_count = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
            fts_count = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
        if code_count != fts_count:
            logger.info(
                "FTS parity mismatch (code_chunks=%s, chunks_fts=%s); rebuilding",
                code_count,
                fts_count,
            )
            return self._db.rebuild_fts()
        return int(fts_count)

    def _indexing_policy_changed(
        self,
        root_path: Path,
        include_tests: bool,
        include_resources: bool,
        resource_extensions: tuple[str, ...] | None,
        exclusion_patterns: set[str] | None,
    ) -> bool:
        """Return whether the current indexing policy differs from the last run.

        Compares the discovery-affecting parameters against the values recorded
        at index time; a mismatch means previously-indexed files may no longer
        be eligible and the stale-file sweep must run.

        Returns:
            ``True`` when any discovery parameter changed since the last index.
        """
        return (
            self._metadata.get("index_root") != str(root_path.resolve())
            or self._metadata.get("index_include_tests") != str(include_tests).lower()
            or self._metadata.get("index_include_resources") != str(include_resources).lower()
            or tuple(self._metadata.get_json("index_resource_extensions") or [])
            != tuple(resource_extensions or [])
            or set(self._metadata.get_json("index_exclusion_patterns") or [])
            != set(exclusion_patterns or [])
            or self._metadata.get("index_prose") != str(self._settings.index_prose).lower()
        )

    def _insert_chunk(self, chunk: dict[str, Any], _source_bytes: bytes) -> int | None:
        """Insert a single chunk row, computing its subword tokens + checksum.

        Computes the ``subwords`` field (via ``identify_subwords``) and a
        content-derived ``tokens_checksum`` for dedup, then upserts into
        ``code_chunks`` (keyed on ``UNIQUE(file_path, line_start)``). FTS is
        kept in sync by the maintenance triggers.

        Args:
            chunk: The parsed chunk dict from the worker results.
            _source_bytes: Unused; retained for API compatibility.

        Returns:
            The new/replaced row id, or ``None`` when the insert fails.
        """
        content = chunk.get("content", "")
        tokens_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        subwords = " ".join(identify_subwords(content))
        declared_rules = chunk.get("declared_rules") or ""
        content_type = (
            chunk.get("content_type") or classify_content_type(chunk.get("file_path", "")).value
        )
        with self._db.write_transaction() as conn:
            try:
                cursor = conn.execute(
                    "INSERT OR REPLACE INTO code_chunks "
                    "(fqn, file_path, line_start, line_end, "
                    "content, language, is_definition, chunk_type, "
                    "chunk_node_type, subwords, declared_rules, tokens_checksum, "
                    "content_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        chunk.get("fqn", ""),
                        chunk["file_path"],
                        chunk["line_start"],
                        chunk["line_end"],
                        content,
                        chunk.get("language", "unknown"),
                        1 if chunk.get("is_definition", False) else 0,
                        chunk.get("chunk_type", "ast"),
                        chunk.get("chunk_node_type"),
                        subwords,
                        declared_rules,
                        tokens_hash,
                        content_type,
                    ),
                )
                # chunks_fts is kept in sync by the FTS5 maintenance triggers;
                # a final rebuild_fts() guarantees parity after the batch.
                return cursor.lastrowid
            except Exception as exc:
                logger.warning(
                    "Failed to insert chunk for %s:%d: %s",
                    chunk.get("file_path"),
                    chunk.get("line_start"),
                    exc,
                )
                return None

    def _remove_file(self, file_path: str) -> int:
        """Remove all DB + vector rows for *file_path*; returns rows removed."""
        removed = 0
        with self._db.write_transaction() as conn:
            chunk_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM code_chunks WHERE file_path = ?;", (file_path,)
                ).fetchall()
            ]
            for cid in chunk_ids:
                self._vector_index.remove(cid)
            sym_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM symbols WHERE file_path = ?;", (file_path,)
                ).fetchall()
            ]
            if sym_ids:
                ph = ",".join("?" for _ in sym_ids)
                conn.execute(
                    f"DELETE FROM graph_edges "
                    f"WHERE source_symbol_id IN ({ph}) OR target_symbol_id IN ({ph});",
                    sym_ids + sym_ids,
                )
            conn.execute("DELETE FROM code_chunks WHERE file_path = ?;", (file_path,))
            conn.execute("DELETE FROM chunks_fts WHERE file_path = ?;", (file_path,))
            conn.execute("DELETE FROM symbols WHERE file_path = ?;", (file_path,))
            conn.execute("DELETE FROM file_checksums WHERE file_path = ?;", (file_path,))
            removed = len(chunk_ids) + len(sym_ids)
        return removed

    def _sweep_stale_files(self, root_path: Path) -> int:
        """Prune rows for files that no longer exist or now fall under exclusions."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT file_path FROM file_checksums "
                "UNION SELECT DISTINCT file_path FROM code_chunks "
                "UNION SELECT DISTINCT file_path FROM symbols;"
            ).fetchall()
        removed_total = 0
        for row in rows:
            fp = row["file_path"]
            if not fp:
                continue
            path = Path(fp)
            gone = not path.exists()
            excluded = self._parser.is_excluded_file(path, root_path)
            if gone or excluded:
                removed_total += self._remove_file(fp)
        return removed_total

    def prune_stale_files(
        self,
        root_path: Path,
        include_tests: bool = True,
        include_resources: bool = True,
        resource_extensions: tuple[str, ...] | None = None,
        exclusion_patterns: set[str] | None = None,
    ) -> dict[str, Any]:
        """Prune index rows for files no longer on disk or indexable.

        Only runs the sweep against an existing index and returns a summary —
        no re-indexing is performed.
        """
        res_exts = resource_extensions if include_resources else None
        discoverable = {
            str(p)
            for p in self._parser.discover_files(
                root_path,
                exclusion_patterns,
                include_resources=include_resources,
                resource_extensions=res_exts,
                index_prose=self._settings.index_prose,
            )
        }
        if not include_tests:
            discoverable = {p for p in discoverable if not _is_test_file(p)}
        discoverable_resolved = {str(Path(p).resolve()) for p in discoverable}

        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT file_path FROM file_checksums "
                "UNION SELECT DISTINCT file_path FROM code_chunks "
                "UNION SELECT DISTINCT file_path FROM symbols;"
            ).fetchall()
        removed = 0
        for row in rows:
            fp = row["file_path"]
            if not fp:
                continue
            if not Path(fp).exists() or str(Path(fp).resolve()) not in discoverable_resolved:
                removed += self._remove_file(fp)
        self._metadata.set("last_pruned_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        return {"pruned_files": removed}

    @staticmethod
    def _resolve_chunk_fqn(chunk: dict[str, Any], symbols: list[dict[str, Any]]) -> str:
        """Stamp *chunk* with the FQN of its most specific enclosing symbol.

        Thin wrapper over the module-level :func:`_resolve_chunk_fqn` so
        callers can invoke it through the orchestrator.

        Args:
            chunk: The chunk dict to stamp.
            symbols: Candidate symbol dicts that may contain the chunk.

        Returns:
            The resolved FQN string.
        """
        return _resolve_chunk_fqn(chunk, symbols)

    @staticmethod
    def _strip_params(fqn: str) -> str:
        """Strip a trailing ``(params)`` list from an FQN (Java signatures)."""
        idx = fqn.find("(")
        return fqn[:idx] if idx != -1 else fqn

    @staticmethod
    def _declaration_line_from_range(source_range: str | None) -> int | None:
        """Extract the starting line from a ``[s_line,s_col,e_line,e_col]`` JSON range."""
        if not source_range:
            return None
        try:
            import json as _json

            parts = _json.loads(source_range)
            if isinstance(parts, list) and parts:
                return int(parts[0])
        except Exception:
            return None
        return None

    @staticmethod
    def _call_is_recursive(conn: Any, symbol_id: int, call_line: int | None) -> bool:
        """Return whether a ``source == target`` edge is a genuine recursive self-call.

        A recursive self-call has its call location inside the symbol's own
        declaration range — the method calls itself from within its body.
        """
        if call_line is None:
            return False
        row = conn.execute(
            "SELECT line_start, line_end FROM symbols WHERE id = ?;", (symbol_id,)
        ).fetchone()
        if row is None or row["line_start"] is None or row["line_end"] is None:
            return False
        return int(row["line_start"]) <= call_line <= int(row["line_end"])

    def _resolve_cross_file_target(
        self,
        conn: Any,
        target_fqn: str,
        source_fqn: str,
        source_range: str | None,
    ) -> int | None:
        """Resolve an unresolved cross-file edge target to a persisted symbol id.

        Ordering (replacing the ``ORDER BY id LIMIT 1`` ambiguity bug):
          1. exact FQN match
          2. conventional-FQN match (param-stripped)
          3. same-file symbol (target declared in the caller's file)
          4. declaration-range match (candidate whose declaration range
             contains the resolved call range's start line)
          5. ``ORDER BY id`` fallback (only when a unique best candidate exists
             per tier; ties resolve to the lowest id)
        """
        resolved = self._resolve_cross_file_symbol(conn, target_fqn, source_fqn, source_range)
        return resolved[0] if resolved else None

    def _resolve_cross_file_symbol(
        self,
        conn: Any,
        symbol_fqn: str,
        source_fqn: str | None = None,
        source_range: str | None = None,
        type_only: bool = False,
    ) -> tuple[int | None, str | None]:
        """Resolve *symbol_fqn* against persisted symbols, returning ``(id, tier)``.

        Tier names match the persisted ``resolution_tier`` vocabulary:
        ``exact``, ``conventional``, ``same_file``, ``range``, ``fallback``.

        Args:
            conn: An open graph connection.
            symbol_fqn: The target name to resolve.
            source_fqn: FQN of the referencing symbol (for same-file/range tiers).
            source_range: Source range of the reference.
            type_only: When ``True`` the target names a type declaration (an
                inheritance base), so a dotted import-map path that does not
                byte-match a symbol may fall back to the unique type sharing
                its leaf name. Receiver-qualified call targets keep the default
                ``False`` and never fall through to that fallback.
        """
        if not symbol_fqn:
            return None, None
        simple = symbol_fqn.rsplit(".", 1)[-1] if "." in symbol_fqn else symbol_fqn
        source_path = source_fqn.split("::", 1)[0] if source_fqn and "::" in source_fqn else ""
        call_line = self._declaration_line_from_range(source_range)
        stripped = self._strip_params(symbol_fqn)

        rows = conn.execute(
            "SELECT s.id, s.fqn, s.conventional_fqn, s.file_path, s.line_start, s.line_end, "
            "s.kind, p.name AS parent_name "
            "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
            "WHERE s.name = ? ORDER BY s.id;",
            (simple,),
        ).fetchall()

        exact = [r for r in rows if r["fqn"] == symbol_fqn]
        if exact:
            return int(exact[0]["id"]), "exact"

        conv = [
            r
            for r in rows
            if r["conventional_fqn"] and self._strip_params(r["conventional_fqn"]) == stripped
        ]
        if conv:
            return int(conv[0]["id"]), "conventional"

        # Qualified-name tier: a dotted target like ``AuthService.authenticate``
        # names its enclosing class, so it must resolve to the symbol whose
        # parent class matches, NOT to a same-named method in the caller's file.
        class_part = None
        if "." in symbol_fqn and not symbol_fqn.startswith("::"):
            class_part = self._strip_params(symbol_fqn).rsplit(".", 1)[0]
            if class_part:
                qualified = [
                    r
                    for r in rows
                    if r["parent_name"] == class_part
                    and self._strip_params(r["fqn"]).endswith(symbol_fqn)
                ]
                if qualified:
                    return int(qualified[0]["id"]), "conventional"

        # A receiver-qualified call target (e.g. ``repository.save`` or
        # ``articleService.save``) must NEVER merge onto a same-named method of
        # a different receiver via the ``same_file``/``range``/``fallback``
        # tiers. Only a receiver whose enclosing type matches the callee's may
        # attach; an unknown receiver yields no edge, never a wrong one.
        if class_part is not None:
            same_qualified = [
                r
                for r in rows
                if source_path and r["file_path"] == source_path and r["parent_name"] == class_part
            ]
            if same_qualified:
                return int(same_qualified[0]["id"]), "same_file"
            if type_only:
                typed = [r for r in rows if (r["kind"] or "") in _TYPE_DECLARATION_KINDS]
                if len(typed) == 1:
                    return int(typed[0]["id"]), "fallback"
            return None, None

        same_file = [r for r in rows if source_path and r["file_path"] == source_path]
        if same_file:
            return int(same_file[0]["id"]), "same_file"

        if call_line is not None:
            decl = [
                r
                for r in rows
                if r["line_start"] is not None
                and r["line_end"] is not None
                and r["line_start"] <= call_line <= r["line_end"]
            ]
            if decl:
                return int(decl[0]["id"]), "range"

        if len(rows) == 1:
            return int(rows[0]["id"]), "fallback"
        if type_only:
            typed = [r for r in rows if (r["kind"] or "") in _TYPE_DECLARATION_KINDS]
            if len(typed) == 1:
                return int(typed[0]["id"]), "fallback"
        if rows:
            logger.debug(
                "Dropping ambiguous cross-file symbol %r (%d candidates)",
                symbol_fqn,
                len(rows),
            )
        return None, None
