"""Index orchestrator — coordinates full and incremental codebase indexing.

Walks discovered source files, extracts symbols + edges via AST, chunks code,
generates embeddings, and persists everything to the graph database and vector index.
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import os
import posixpath
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_search.engine.classification import content_type as classify_content_type
from code_search.engine.config import Settings, _is_test_file
from code_search.engine.embed_representation import (
    REPRESENTATION_SCHEME_VERSION,
    build_embed_text,
    derive_enclosing_context,
)
from code_search.engine.embeddings import (
    EmbeddingGenerator,
    VectorIndex,
    get_representation_scheme_version,
    set_representation_scheme_version,
)
from code_search.engine.graph import (
    INDEX_FORMAT_VERSION,
    SCHEMA_VERSION,
    DocLinkStore,
    EdgeStore,
    GraphDatabase,
    IndexMetadataStore,
    ModuleEdgeStore,
    RationaleStore,
)
from code_search.engine.graph_passes import (
    derive_interface_dispatch_edges,
    rebuild_derived_graph_data,
)
from code_search.engine.parser import ASTParser
from code_search.engine.parser import _is_lockfile as _is_lockfile_path
from code_search.engine.paths import repo_relative_path
from code_search.engine.search import identify_subwords
from code_search.engine.symbols import SymbolExtractor, SymbolStore

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

# Chunks per ``encode_batch`` call during the embedding phase. Encoding runs
# one sentence at a time regardless (``batch_size=1``), so splitting the call
# yields identical vectors while giving the progress callback a periodic tick.
_EMBED_PROGRESS_BATCH = 256

# Files per persistence transaction. Committing per file still pays one commit
# per file, which dominates large builds on slow disks; grouping files keeps
# each transaction small enough to bound the WAL while cutting commit count by
# this factor. A crash loses at most one group, which a full rebuild redoes.
_PERSIST_COMMIT_BATCH = 256

#: Maximum characters retained from a lockfile in its single infra record.
_LOCKFILE_CHUNK_CHARS = 2000

# Reports pipeline progress as ``(phase, completed, total)``. ``phase`` is one
# of ``"parsing"``, ``"persisting"``, or ``"embedding"``.
ProgressCallback = Callable[[str, int, int], None]

# Maximum number of placeholders per ``IN (...)`` query. SQLite's historic
# ``SQLITE_MAX_VARIABLE_NUMBER`` default is 999 (32766 on newer builds); staying
# under it keeps cross-file edge resolution correct on large indexes.
_SQL_VAR_LIMIT = 900

# Upper bound on error spans retained per file. A pathologically malformed file
# cannot inflate the coverage table beyond this many ranges.
_MAX_COVERAGE_RANGES = 50


def _chunked(items: list[str], size: int) -> list[list[str]]:
    """Split *items* into consecutive sublists of at most *size* elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _base_type_name(raw: str | None) -> str:
    """Reduce a declared/base type reference to its simple leaf name.

    Strips generic arguments before the last ``.``/``::`` segment so
    ``java.util.List<Order>`` and ``ExtensionManager<Handler>`` both name a
    type symbol by its declaration name.
    """
    if not raw:
        return ""
    text = raw.strip()
    if "<" in text:
        text = text.split("<", 1)[0].strip()
    for separator in ("::", "."):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    return text.strip()


class _TypeHierarchy:
    """In-memory type ancestry used while resolving receiver-qualified calls.

    A call such as ``extensionManager.getProxy()`` names the declared field
    type, but ``getProxy`` may be declared on a superclass or interface. The
    hierarchy mirrors the edges being persisted in this run, including the
    unresolved cross-file bases that are still waiting for their own
    resolution, so a method inherited from a supertype can be found without a
    second indexing pass.
    """

    def __init__(
        self,
        types_by_name: dict[str, list[dict[str, str]]],
        bases_by_fqn: dict[str, set[str]],
    ) -> None:
        self._types_by_name = types_by_name
        self._bases_by_fqn = bases_by_fqn

    def ancestor_name_levels(
        self,
        class_part: str,
        class_leaf: str,
        source_path: str,
    ) -> list[set[str]]:
        """Return ancestor type names nearest-first for *class_part*.

        Args:
            class_part: The receiver's declared type as written in the call
                target (a simple name or an import-path spelling).
            class_leaf: The final segment of *class_part*.
            source_path: The caller's file, used to disambiguate a same-file
                type from an unrelated same-named one.

        Returns:
            One set of type simple names per ancestry level. An empty list
            means the declared type is unknown or ambiguous; callers then keep
            the reference unresolved rather than guessing.
        """
        start = self._resolve_start(class_part, class_leaf, source_path)
        if start is None:
            return []
        levels: list[set[str]] = []
        frontier = {start}
        seen = {start}
        for _ in range(6):
            next_fqns: set[str] = set()
            next_names: set[str] = set()
            for fqn in frontier:
                for base in sorted(self._bases_by_fqn.get(fqn, ())):
                    for info in self._types_by_name.get(base, ()):
                        base_fqn = info["fqn"]
                        if base_fqn in seen:
                            continue
                        seen.add(base_fqn)
                        next_fqns.add(base_fqn)
                        next_names.add(info["name"])
            if not next_names:
                break
            levels.append(next_names)
            frontier = next_fqns
        return levels

    def _resolve_start(
        self,
        class_part: str,
        class_leaf: str,
        source_path: str,
    ) -> str | None:
        """Return the type FQN *class_part* names, or ``None`` when ambiguous."""
        candidates = self._types_by_name.get(class_leaf, [])
        if not candidates:
            return None
        if "." in class_part or "::" in class_part:
            for info in candidates:
                conventional = info.get("conventional_fqn") or ""
                if conventional and conventional == class_part:
                    return info["fqn"]
            dotted_path = class_part.replace("::", ".").replace(".", "/")
            path_matches = [info for info in candidates if info["file_path"].endswith(dotted_path)]
            if len(path_matches) == 1:
                return path_matches[0]["fqn"]
        same_file = [info for info in candidates if info["file_path"] == source_path]
        if len(same_file) == 1:
            return same_file[0]["fqn"]
        if len(candidates) == 1:
            return candidates[0]["fqn"]
        return None


def _build_type_hierarchy(
    conn: Any,
    pending_edges: list[dict[str, Any]],
) -> _TypeHierarchy:
    """Build the type-ancestry map for cross-file edge resolution.

    Uses persisted symbols and inheritance edges plus the still-pending
    cross-file bases from this run. Each base is stored by simple type name, so
    an import-map spelling (``pkg.Base``) and a bare base (``Base``) match the
    same declared type.
    """
    types_by_name: dict[str, list[dict[str, str]]] = {}
    type_fqns: set[str] = set()
    placeholders = ",".join("?" for _ in _TYPE_DECLARATION_KINDS)
    for row in conn.execute(
        f"SELECT fqn, name, kind, file_path, conventional_fqn FROM symbols "
        f"WHERE kind IN ({placeholders});",
        tuple(sorted(_TYPE_DECLARATION_KINDS)),
    ):
        info = {
            "fqn": str(row["fqn"]),
            "name": str(row["name"]),
            "file_path": str(row["file_path"] or ""),
            "conventional_fqn": str(row["conventional_fqn"] or ""),
        }
        type_fqns.add(info["fqn"])
        types_by_name.setdefault(info["name"], []).append(info)

    bases_by_fqn: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT src.fqn AS source_fqn, tgt.name AS base_name "
        "FROM graph_edges e "
        "JOIN symbols src ON src.id = e.source_symbol_id "
        "JOIN symbols tgt ON tgt.id = e.target_symbol_id "
        "WHERE e.edge_type IN ('INHERITS', 'IMPLEMENTS') AND e.resolved = 1 "
        "AND e.target_symbol_id IS NOT NULL;"
    ):
        base = _base_type_name(row["base_name"])
        if base:
            bases_by_fqn.setdefault(str(row["source_fqn"]), set()).add(base)

    for edge in pending_edges:
        if edge.get("edge_type") not in ("INHERITS", "IMPLEMENTS"):
            continue
        source_fqn = str(edge.get("source_fqn") or "")
        if source_fqn not in type_fqns:
            continue
        base = _base_type_name(edge.get("target_fqn") or edge.get("target_raw"))
        if base:
            bases_by_fqn.setdefault(source_fqn, set()).add(base)
    return _TypeHierarchy(types_by_name, bases_by_fqn)


# Reports a human-readable status message for a single, non-iterable pipeline
# step (for example the post-embedding finalization). Used to keep the user
# informed about work that has no natural ``(completed, total)`` counter.
StatusCallback = Callable[[str], None]

# Symbol kinds that declare a type. Used when resolving an inheritance base
# that an import map expanded to a dotted module path (for example a Python
# ``from pkg.animal import Animal`` -> ``pkg.animal.Animal``): the base names a
# type, never a receiver-qualified ``Class.method``, so the resolver may fall
# back to the unique type declaration sharing its leaf name.
_TYPE_DECLARATION_KINDS = {"class", "interface", "enum", "type_alias"}

#: Symbol kinds that can be invoked. A ``CALL_REFERENCE`` whose target is not
#: callable is downgraded to ``USAGE``: the value was referenced, not called.
_CALLABLE_KINDS = {"function", "method", "constructor", "class"}

#: Comment markers promoted to first-class rationale evidence.
_RATIONALE_MARKERS = re.compile(r"\b(NOTE|WHY|HACK|TODO|FIXME|ADR|RFC)\b", re.IGNORECASE)


#: Lines that look like comments (the marker must appear in comment text).
_COMMENT_PREFIX = re.compile(r"^\s*(#|//|/\*|\*|--|<!--)")

#: Prose formats whose structure is marked by headings instead of blank-line
#: blocks. Splitting these by heading returns focused passages rather than one
#: chunk spanning the whole file.
_HEADING_PROSE_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".adoc"})
_ATX_HEADING = re.compile(r"^#{1,6}\s+\S")
_ADOC_HEADING = re.compile(r"^={1,6}\s+\S")
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_SETEXT_UNDERLINE = re.compile(r"^\s*([=\-~^\"'])\1{2,}\s*$")


def _extract_rationale(
    file_path: Path, source_bytes: bytes, symbols: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract ``NOTE``/``WHY``/``HACK``/``TODO``/``FIXME``/ADR comments.

    Each matching comment line is attached to the smallest (nearest) enclosing
    symbol by declaration line range. ``ADR``/``RFC`` references both map to
    the ``adr`` kind; other markers map to their lowercase marker name.
    """
    text = source_bytes.decode("utf-8", errors="replace")
    rationale: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines()):
        if not _COMMENT_PREFIX.match(line):
            continue
        match = _RATIONALE_MARKERS.search(line)
        if match is None:
            continue
        marker = match.group(1).lower()
        kind = "adr" if marker in ("adr", "rfc") else marker
        enclosing: dict[str, Any] | None = None
        best_span: int | None = None
        for symbol in symbols:
            start = symbol.get("line_start")
            end = symbol.get("line_end")
            if start is None or end is None or not (start <= index <= end):
                continue
            span = end - start
            if best_span is None or span < best_span:
                enclosing = symbol
                best_span = span
        if enclosing is None:
            continue
        rationale.append(
            {
                "fqn": enclosing.get("fqn", ""),
                "file_path": str(file_path),
                "line_start": index,
                "line_end": index,
                "kind": kind,
                "text": line.strip(),
            }
        )
    return rationale


def _collect_error_ranges(tree: Any, source_bytes: bytes) -> tuple[list[list[int]], bool]:
    """Return tree-sitter error ranges as 1-based inclusive line spans.

    The ranges are merged and capped so a file with thousands of tiny syntax
    errors cannot blow up the coverage row. A file is ``unusable`` when the
    union of its error spans covers at least 80% of its lines: the structural
    extraction is then too incomplete to trust.

    Args:
        tree: A tree-sitter tree, or ``None`` when parsing was unavailable.
        source_bytes: The exact source that produced *tree*.

    Returns:
        ``(line_ranges, unusable)`` where each range is ``[start, end]`` using
        1-based line numbers.
    """
    if tree is None:
        return [], False
    root = tree.root_node
    if not root.has_error:
        return [], False

    raw: list[tuple[int, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            raw.append((int(node.start_point[0]), int(node.end_point[0])))
            continue
        stack.extend(reversed(node.children))

    merged: list[list[int]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    ranges = [[start + 1, end + 1] for start, end in merged[:_MAX_COVERAGE_RANGES]]
    total_lines = source_bytes.count(b"\n") + 1
    covered = sum(end - start + 1 for start, end in merged)
    return ranges, bool(merged) and covered / max(total_lines, 1) >= 0.8


def _process_file_worker(args: tuple[Path, bytes, str, tuple[str, ...] | None]) -> dict[str, Any]:
    """Standalone pickle-safe worker for parallel AST parsing.

    Accepts ``(file_path, source_bytes, language, resource_extensions)``
    and returns a serialisable dict with symbols, edges, chunks, and metadata.
    """
    file_path, source_bytes, language, resource_extensions = args
    from code_search.engine.parser import ASTParser
    from code_search.engine.symbols import SymbolExtractor

    parser = ASTParser()
    extractor = SymbolExtractor(parser)

    is_resource = language in {"xml", "sql", "properties", "gradle", "dockerfile", "makefile"}
    if _is_lockfile_path(file_path):
        syms = []
        edges = []
        chunks = [_lockfile_chunk(file_path, source_bytes, language)]
    else:
        syms = extractor.extract_symbols(file_path, source_bytes)
        edges = extractor.extract_edges(file_path, source_bytes)
        chunks = parser.get_chunks_for_file(file_path, source_bytes)
    parse_failed = False
    if not chunks and not _is_lockfile_path(file_path):
        if file_path.suffix.lower() in _HEADING_PROSE_EXTENSIONS:
            chunks = _prose_heading_chunks(file_path, source_bytes, language)
        if not chunks:
            if is_resource or language in {"unknown"}:
                chunks = _fallback_chunk_file(file_path, source_bytes, language, 100)
            else:
                chunks = _module_fallback_chunk(file_path, source_bytes, language)
                parse_failed = file_path.suffix.lower() not in (resource_extensions or ())
    # Parse-error coverage: reuse the tree the extractor already produced. A
    # file with ERROR/MISSING ranges is indexed partially; one whose errors
    # cover most of the file is recorded as unusable.
    tree = parser.parse_file(file_path, source_bytes=source_bytes)
    error_ranges, parse_unusable = _collect_error_ranges(tree, source_bytes)
    parse_failed = parse_failed or parse_unusable
    for chunk in chunks:
        if is_resource:
            chunk["chunk_type"] = "resource"
            chunk["chunk_node_type"] = "raw_text"
        chunk["content_type"] = classify_content_type(file_path).value
        if _is_lockfile_path(file_path):
            chunk["fqn"] = f"{file_path}::lockfile"
        else:
            chunk["fqn"] = _resolve_chunk_fqn(chunk, syms)
        chunk["embed_context"] = derive_enclosing_context(chunk, syms)
    rationale = _extract_rationale(file_path, source_bytes, syms)
    content_hash = hashlib.sha256(source_bytes).hexdigest()

    return {
        "file_path": str(file_path),
        "symbols": syms,
        "edges": edges,
        "chunks": chunks,
        "rationale": rationale,
        "content_hash": content_hash,
        "parse_failed": parse_failed,
        "parse_error_ranges": error_ranges,
        "parse_unusable": parse_unusable,
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


def _relative_path(file_path: str, root_path: Path | None) -> str:
    """Return *file_path* relative to *root_path*, or unchanged when outside it."""
    return repo_relative_path(file_path, root_path)


def _relative_fqn(fqn: str, file_path: str, root_path: Path | None) -> str:
    """Return *fqn* with its absolute file-path prefix made repo-relative.

    Symbol FQNs embed the absolute file path for path-prefixed languages and
    raw chunks (``{file_path}::{symbol}``). The keyword index stores this
    relative form so its length normalisation cannot depend on where the
    repository was checked out. Dotted FQNs (``com.example.Type``) carry no
    path and are returned unchanged.

    Args:
        fqn: The absolute-path FQN.
        file_path: The chunk's absolute file path.
        root_path: The repository root, or ``None`` when unknown.

    Returns:
        The repo-relative FQN when it can be derived, else *fqn*.
    """
    if not fqn or not file_path or root_path is None:
        return fqn
    if not fqn.startswith(file_path):
        return fqn
    relative = _relative_path(file_path, root_path)
    if relative == file_path:
        return fqn
    return relative + fqn[len(file_path) :]


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


def _prose_heading_chunks(
    file_path: Path, source_bytes: bytes, language: str = "unknown", max_chunk_lines: int = 100
) -> list[dict[str, Any]]:
    """Split heading-structured prose into one chunk per section.

    Markdown ATX/setext headings, AsciiDoc headings, and reStructuredText
    underlines start a new section; headings inside fenced code blocks are
    ignored. Each section keeps its exact line span so a prose query returns
    the passage that answers it instead of the whole document. Sections longer
    than *max_chunk_lines* are split into line blocks to stay within the
    embedding budget. Files with no headings return an empty list so the
    caller can fall back to whole-file chunking.

    Args:
        file_path: Path of the prose file being chunked.
        source_bytes: Raw file bytes decoded as UTF-8 with replacement.
        language: Language label stamped on each emitted chunk.
        max_chunk_lines: Maximum lines per emitted chunk.

    Returns:
        Chunks with ``chunk_type``/``chunk_node_type`` ``raw_text``, or an
        empty list when the document has no detectable heading.
    """
    lines = source_bytes.decode("utf-8", errors="replace").split("\n")
    headings: list[int] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        fence_match = _FENCE_OPEN.match(line)
        if fence is not None:
            if fence_match and fence_match.group(1).startswith(fence):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            continue
        if (
            _ATX_HEADING.match(line)
            or _ADOC_HEADING.match(line)
            or (
                line.strip()
                and index + 1 < len(lines)
                and _SETEXT_UNDERLINE.match(lines[index + 1])
            )
        ):
            headings.append(index)
    if not headings:
        return []

    boundaries = sorted({0, *headings})
    chunks: list[dict[str, Any]] = []
    for position, start in enumerate(boundaries):
        end = boundaries[position + 1] if position + 1 < len(boundaries) else len(lines)
        section = lines[start:end]
        while section and not section[-1].strip():
            section.pop()
        if not any(line.strip() for line in section):
            continue
        for offset in range(0, len(section), max_chunk_lines):
            block = section[offset : offset + max_chunk_lines]
            content = "\n".join(block)
            if not content.strip():
                continue
            block_start = start + offset
            chunks.append(
                {
                    "file_path": str(file_path),
                    "line_start": block_start,
                    "line_end": block_start + len(block) - 1,
                    "content": content,
                    "language": language,
                    "is_definition": False,
                    "chunk_type": "raw_text",
                    "chunk_node_type": "raw_text",
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


def _lockfile_chunk(file_path: Path, source_bytes: bytes, language: str) -> dict[str, Any]:
    """Build the single infra record for a package lockfile.

    Lockfiles can span tens of thousands of lines and carry no code the graph
    can use. Indexing them line-block by line-block floods the candidate pool
    with near-duplicate dependency rows that dense retrieval cannot tell apart
    from source. A lockfile is therefore represented by one bounded,
    non-definition ``infra`` chunk so it stays findable by literal dependency
    evidence without competing on chunk count.

    Args:
        file_path: The lockfile path.
        source_bytes: Raw lockfile bytes.
        language: The detected language token (``json``/``yaml``/...).

    Returns:
        A one-element chunk list describing the lockfile.
    """
    text = source_bytes.decode("utf-8", errors="replace")
    excerpt = text[:_LOCKFILE_CHUNK_CHARS]
    line_count = text.count("\n")
    return {
        "file_path": str(file_path),
        "line_start": 0,
        "line_end": max(0, min(line_count, excerpt.count("\n"))),
        "content": excerpt,
        "language": language,
        "is_definition": False,
        "chunk_type": "infra",
        "chunk_node_type": "lockfile",
    }


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
        self._module_store = ModuleEdgeStore(db)
        self._rationale_store = RationaleStore(db)
        self._doc_link_store = DocLinkStore(db)
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
        progress_callback: ProgressCallback | None = None,
        status_callback: StatusCallback | None = None,
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
            progress_callback: Optional ``(phase, completed, total)`` reporter
                invoked periodically through the parsing, persistence, and
                embedding phases. Phases are labelled ``parsing``,
                ``persisting``, and ``embedding``.
            status_callback: Optional ``(message)`` reporter invoked once per
                non-iterable finalization step (saving vectors, sweeping stale
                files, rebuilding the keyword index, validating edges) so the
                user is informed about work that has no progress counter.

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
            stored_format = self._metadata.get_int("index_format_version")
            if stored_format is None or stored_format < INDEX_FORMAT_VERSION:
                force = True
                incremental = False
                logger.info(
                    "Index format %s (required %s) requires re-index. Forcing full re-index.",
                    stored_format,
                    INDEX_FORMAT_VERSION,
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
                from code_search.engine.embeddings import _emit_warning_once

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
            max_bytes = max(1, self._settings.max_file_bytes)
            oversized: list[Path] = []
            within_limits: list[Path] = []
            coverage_events: list[dict[str, Any]] = []
            for candidate in all_files:
                try:
                    if candidate.stat().st_size > max_bytes:
                        oversized.append(candidate)
                        coverage_events.append(
                            {
                                "file_path": str(candidate),
                                "kind": "skipped_oversized",
                                "detail": f"size exceeds max_file_bytes={max_bytes}",
                            }
                        )
                        continue
                except OSError as exc:
                    coverage_events.append(
                        {
                            "file_path": str(candidate),
                            "kind": "skipped_read",
                            "detail": f"stat failed: {exc.__class__.__name__}",
                        }
                    )
                    continue
                within_limits.append(candidate)
            all_files = within_limits
            if oversized:
                logger.info("Skipping %d files larger than %d bytes", len(oversized), max_bytes)

            if not incremental:
                self._vector_index.clear()
                # Suspend the FTS triggers before clearing code_chunks. A
                # previous run that was interrupted after suspending them can
                # leave chunks_fts out of sync with code_chunks; the delete
                # triggers would then try to remove rows from an inconsistent
                # external-content index and fail with "database disk image is
                # malformed", making the index unrecoverable.
                self._db.set_fts_triggers(False)
                try:
                    with self._db.write_transaction() as conn:
                        conn.execute("DELETE FROM graph_edges;")
                        conn.execute("DELETE FROM symbols;")
                        conn.execute("DELETE FROM code_chunks;")
                        conn.execute("DELETE FROM chunks_fts;")
                        conn.execute("DELETE FROM paths_fts;")
                        conn.execute("DELETE FROM file_checksums;")
                        conn.execute("DELETE FROM module_edges;")
                        conn.execute("DELETE FROM symbol_rationale;")
                        conn.execute("DELETE FROM doc_links;")
                        conn.execute("DELETE FROM symbol_degrees;")
                except BaseException:
                    self._db.set_fts_triggers(True)
                    raise

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
                        orphan_chunk_ids = [r["id"] for r in orphan_chunks]
                        if orphan_chunk_ids:
                            ph = ",".join("?" for _ in orphan_chunk_ids)
                            conn.execute(
                                f"DELETE FROM doc_links WHERE doc_chunk_id IN ({ph}) "
                                f"OR code_chunk_id IN ({ph});",
                                orphan_chunk_ids + orphan_chunk_ids,
                            )
                        conn.execute("DELETE FROM code_chunks WHERE file_path = ?;", (orphan,))
                        orphan_relative = self._relative_module_path(orphan, root_path)
                        conn.execute(
                            "DELETE FROM module_edges WHERE source_path = ? OR target_path = ?;",
                            (orphan_relative, orphan_relative),
                        )
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
                if not incremental:
                    self._db.set_fts_triggers(True)
                fts_count = self._ensure_fts_parity()
                self._metadata.set_fts_chunks(fts_count)
                self._metadata.set(
                    "last_indexed_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                )
                generation = self._compute_index_generation(root_path)
                try:
                    self._persist_coverage(coverage_events, generation, set())
                except Exception as exc:
                    logger.warning("Coverage persistence failed: %s", exc)
                    self._metadata.set("index_generation", generation)
                try:
                    rebuild_derived_graph_data(self._db, root_path, self._settings)
                except Exception as exc:
                    logger.warning("Derived graph passes failed: %s", exc)
                self._metadata.set_int("index_format_version", INDEX_FORMAT_VERSION)
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
                        old_chunk_ids = [r["id"] for r in old_chunks]
                        self._vector_index.remove_many(old_chunk_ids)
                        if old_chunk_ids:
                            ph = ",".join("?" for _ in old_chunk_ids)
                            conn.execute(
                                f"DELETE FROM doc_links WHERE doc_chunk_id IN ({ph}) "
                                f"OR code_chunk_id IN ({ph});",
                                old_chunk_ids + old_chunk_ids,
                            )
                        conn.execute("DELETE FROM code_chunks WHERE file_path = ?;", (fp_str,))
                        changed_relative = self._relative_module_path(fp_str, root_path)
                        conn.execute(
                            "DELETE FROM module_edges WHERE source_path = ? OR target_path = ?;",
                            (changed_relative, changed_relative),
                        )
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
                except Exception as exc:
                    coverage_events.append(
                        {
                            "file_path": str(fp),
                            "kind": "skipped_read",
                            "detail": f"read failed: {exc.__class__.__name__}",
                        }
                    )
                    continue
                lang = self._parser.detect_language(fp, resource_extensions=res_exts) or "unknown"
                worker_args.append((fp, source_bytes, lang, res_exts))

            processed_results: list[dict[str, Any]] = []
            if worker_args:
                parse_total = len(worker_args)
                num_workers = min(os.cpu_count() or 4, parse_total)
                if num_workers > 1 and parse_total >= num_workers * _PARSE_MIN_BATCH_PER_WORKER:
                    with ProcessPoolExecutor(
                        mp_context=_POOL_CTX, max_workers=num_workers
                    ) as executor:
                        for done, result in enumerate(
                            executor.map(_process_file_worker, worker_args), start=1
                        ):
                            processed_results.append(result)
                            if progress_callback is not None:
                                progress_callback("parsing", done, parse_total)
                else:
                    for done, args in enumerate(worker_args, start=1):
                        processed_results.append(_process_file_worker(args))
                        if progress_callback is not None:
                            progress_callback("parsing", done, parse_total)

            # Phase 3 (serial): DB writes.
            # A single writer connection spans the whole loop and each file
            # commits as one transaction (symbols + edges + chunks + checksum),
            # replacing the previous connection-per-statement pattern whose
            # per-commit fsync dominated index wall-clock. A full build has
            # already cleared the tables, so the FTS maintenance triggers are
            # suspended and the keyword index is rebuilt once at the end —
            # per-chunk trigger work would be discarded by that rebuild anyway.
            total_symbols = 0
            total_chunks = 0
            languages: set[str] = set()
            unresolved_edges: list[dict[str, Any]] = []
            import_edges: list[dict[str, Any]] = []
            has_resource_files = False
            processed_paths: set[str] = set()

            persist_total = len(processed_results)
            suspend_fts = not incremental
            try:
                with self._db.write_connection() as wconn:
                    for done, result in enumerate(processed_results, start=1):
                        file_path_str = result["file_path"]
                        processed_paths.add(file_path_str)
                        if result.get("parse_unusable"):
                            coverage_events.append(
                                {
                                    "file_path": file_path_str,
                                    "kind": "parse_unusable",
                                    "detail": "syntax errors cover most of the file",
                                    "line_ranges": json.dumps(
                                        result.get("parse_error_ranges") or []
                                    ),
                                }
                            )
                        elif result.get("parse_error_ranges"):
                            coverage_events.append(
                                {
                                    "file_path": file_path_str,
                                    "kind": "parse_partial",
                                    "detail": (
                                        f"{len(result['parse_error_ranges'])} syntax error range(s)"
                                    ),
                                    "line_ranges": json.dumps(result["parse_error_ranges"]),
                                }
                            )
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
                                logger.warning(
                                    "FQN collision detected: %s in %s", fqn, file_path_str
                                )
                            existing_fqns.add(fqn)

                        id_map = self._symbol_store.insert_symbols_batch(syms, conn=wconn)
                        total_symbols += len(id_map)
                        kind_by_id = {
                            id_map[sym["fqn"]]: str(sym.get("kind") or "")
                            for sym in syms
                            if sym.get("fqn") in id_map
                        }
                        if syms:
                            languages.add(syms[0].get("language", "unknown"))

                        resolved_edges = []
                        for edge in edges:
                            if edge.get("edge_type") == "IMPORTS":
                                import_edges.append(edge)
                                continue
                            src_id = id_map.get(edge["source_fqn"])
                            tgt_fqn = edge["target_fqn"]
                            tgt_id = id_map.get(tgt_fqn)
                            if tgt_id is None and "::" not in tgt_fqn and file_path_str:
                                tgt_id = id_map.get(f"{file_path_str}::{tgt_fqn}")
                            if src_id is not None and tgt_id is not None:
                                edge_type = str(edge["edge_type"])
                                target_kind = kind_by_id.get(tgt_id, "")
                                if (
                                    edge_type == "INHERITS"
                                    and target_kind == "interface"
                                    and kind_by_id.get(src_id) == "class"
                                ):
                                    edge_type = "IMPLEMENTS"
                                elif (
                                    edge_type == "CALL_REFERENCE"
                                    and target_kind not in _CALLABLE_KINDS
                                ):
                                    edge_type = "USAGE"
                                tier = "exact"
                                if edge.get("via") == "import":
                                    tier = "import"
                                elif edge.get("via") == "type_infer":
                                    tier = "type_infer"
                                resolved_edges.append(
                                    {
                                        "source_symbol_id": src_id,
                                        "target_symbol_id": tgt_id,
                                        "edge_type": edge_type,
                                        "source_range": edge.get("source_range"),
                                        "target_range": edge.get("target_range"),
                                        "resolution_tier": tier,
                                        "properties": self._edge_properties(edge, tier),
                                    }
                                )
                            else:
                                unresolved_edges.append(edge)
                        if resolved_edges and self._settings.index_graph:
                            self._edge_store.insert_edges_batch(resolved_edges, conn=wconn)

                        rationale_rows: list[dict[str, Any]] = []
                        for item in result.get("rationale", []):
                            symbol_id = id_map.get(item.get("fqn", ""))
                            if symbol_id is None:
                                continue
                            rationale_rows.append({**item, "symbol_id": symbol_id})
                        if rationale_rows and self._settings.index_graph:
                            self._rationale_store.insert_batch(rationale_rows, conn=wconn)

                        for chunk in chunks:
                            chunk_id = self._insert_chunk(
                                chunk, b"", conn=wconn, root_path=root_path
                            )
                            if chunk_id is not None:
                                total_chunks += 1
                                chunk["_chunk_id"] = chunk_id
                                if chunk.get("chunk_type") == "resource":
                                    has_resource_files = True

                        try:
                            st = Path(file_path_str).stat()
                            size = st.st_size
                            file_mtime_ns = st.st_mtime_ns
                        except OSError:
                            size = None
                            file_mtime_ns = None
                        wconn.execute(
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
                        if done % _PERSIST_COMMIT_BATCH == 0:
                            wconn.commit()

                        if progress_callback is not None:
                            progress_callback("persisting", done, persist_total)
            finally:
                if suspend_fts:
                    self._db.set_fts_triggers(True)

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
                    for fqn_batch in _chunked(source_fqns, _SQL_VAR_LIMIT):
                        placeholders = ",".join("?" for _ in fqn_batch)
                        src_rows = conn.execute(
                            f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
                            fqn_batch,
                        ).fetchall()
                        src_ids.update({r["fqn"]: r["id"] for r in src_rows})
                    tgt_ids: dict[str, int] = {}
                    for fqn_batch in _chunked(target_fqns, _SQL_VAR_LIMIT):
                        placeholders = ",".join("?" for _ in fqn_batch)
                        tgt_rows = conn.execute(
                            f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
                            fqn_batch,
                        ).fetchall()
                        tgt_ids.update({r["fqn"]: r["id"] for r in tgt_rows})
                    batch_edges: list[dict[str, Any]] = []
                    name_rows_cache: dict[str, list[Any]] = {}
                    kind_cache: dict[int, str] = {}
                    type_hierarchy = _build_type_hierarchy(conn, unresolved_edges)
                    for edge in unresolved_edges:
                        edge_src_id: int | None = src_ids.get(edge.get("source_fqn", ""))
                        src_tier: str | None = "exact"
                        if edge_src_id is None:
                            edge_src_id, src_tier, _src_candidates = (
                                self._resolve_cross_file_symbol(
                                    conn,
                                    edge.get("source_fqn", ""),
                                    source_range=edge.get("source_range"),
                                    name_rows_cache=name_rows_cache,
                                )
                            )
                        if edge_src_id is None:
                            continue
                        edge_tgt_id: int | None = tgt_ids.get(edge.get("target_fqn", ""))
                        tgt_tier: str | None = "exact"
                        candidate_count = 1
                        if edge_tgt_id is None:
                            (
                                edge_tgt_id,
                                tgt_tier,
                                candidate_count,
                            ) = self._resolve_cross_file_symbol(
                                conn,
                                edge.get("target_fqn", ""),
                                edge.get("source_fqn", ""),
                                edge.get("source_range"),
                                type_only=edge.get("edge_type") in ("INHERITS", "IMPLEMENTS")
                                or edge.get("target_kind_hint") == "type",
                                receiver_qualified=(
                                    "." in str(edge.get("target_raw") or "")
                                    and not str(edge.get("target_raw") or "")
                                    .lstrip()
                                    .startswith("new ")
                                ),
                                arg_count=edge.get("arg_count"),
                                name_rows_cache=name_rows_cache,
                                type_hierarchy=type_hierarchy,
                            )
                        if edge_tgt_id is None:
                            if not self._settings.capture_unresolved_callees:
                                continue
                            # Persist the unresolved/external reference as a
                            # ``resolved: 0`` edge carrying the raw text instead
                            # of dropping it. An ambiguous reference records its
                            # tier and candidate count; it is never attached to
                            # the first same-named symbol.
                            batch_edges.append(
                                {
                                    "source_symbol_id": edge_src_id,
                                    "target_symbol_id": None,
                                    "edge_type": edge["edge_type"],
                                    "source_range": edge.get("source_range"),
                                    "target_range": edge.get("target_range"),
                                    "resolution_tier": tgt_tier,
                                    "resolved": 0,
                                    "target_raw": edge.get("target_raw")
                                    or edge.get("target_fqn", ""),
                                    "properties": self._edge_properties(
                                        edge,
                                        tgt_tier,
                                        candidate_count=candidate_count,
                                    ),
                                }
                            )
                            continue
                        edge_tier: str | None = src_tier if src_tier != "exact" else tgt_tier
                        via = edge.get("via")
                        if edge_tier == "exact" and via == "import":
                            edge_tier = "import"
                        elif edge_tier == "exact" and via == "type_infer":
                            edge_tier = "type_infer"
                        edge_type = str(edge["edge_type"])
                        target_kind = self._symbol_kind(conn, edge_tgt_id, kind_cache)
                        if (
                            edge_type == "INHERITS"
                            and target_kind == "interface"
                            and self._symbol_kind(conn, edge_src_id, kind_cache) == "class"
                        ):
                            edge_type = "IMPLEMENTS"
                        elif edge_type == "CALL_REFERENCE" and target_kind not in _CALLABLE_KINDS:
                            edge_type = "USAGE"
                        edge_dict: dict[str, Any] = {
                            "source_symbol_id": edge_src_id,
                            "target_symbol_id": edge_tgt_id,
                            "edge_type": edge_type,
                            "source_range": edge.get("source_range"),
                            "target_range": edge.get("target_range"),
                            "resolution_tier": edge_tier,
                            "properties": self._edge_properties(
                                edge, edge_tier, candidate_count=candidate_count
                            ),
                        }
                        if edge_src_id == edge_tgt_id:
                            call_line = self._declaration_line_from_range(edge.get("source_range"))
                            recursive = self._call_is_recursive(conn, edge_src_id, call_line)
                            if not recursive:
                                continue
                            edge_dict["recursive"] = True
                        batch_edges.append(edge_dict)
                    if batch_edges and self._settings.index_graph:
                        self._edge_store.insert_edges_batch(batch_edges)

            if import_edges and self._settings.index_graph:
                try:
                    self._persist_module_edges(Path(root_path), import_edges)
                except Exception as exc:
                    logger.warning("Module edge persistence failed: %s", exc)

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

            doc_embeddings: list[tuple[int, str, Any]] = []
            if embed_args:
                embed_total = len(embed_args)
                for start in range(0, embed_total, _EMBED_PROGRESS_BATCH):
                    batch = embed_args[start : start + _EMBED_PROGRESS_BATCH]
                    embed_texts = [text for text, _, _, _, _ in batch]
                    embed_vectors = self._embedding_generator.encode_batch(embed_texts)
                    for (_, chunk_id, file_path, fqn, content_type), embedding in zip(
                        batch, embed_vectors, strict=True
                    ):
                        if embedding is not None:
                            self._vector_index.add(
                                chunk_id,
                                embedding,
                                {"file_path": file_path, "fqn": fqn, "content_type": content_type},
                            )
                            if (
                                self._settings.index_graph
                                and self._settings.index_doc_links
                                and content_type
                                in (
                                    "docs",
                                    "config",
                                )
                            ):
                                doc_embeddings.append((chunk_id, file_path, embedding))
                    if progress_callback is not None:
                        progress_callback(
                            "embedding", min(start + len(batch), embed_total), embed_total
                        )

            if status_callback is not None:
                status_callback("Saving vectors")
            self._vector_index.save()
            if doc_embeddings:
                if status_callback is not None:
                    status_callback("Linking documentation")
                try:
                    self._persist_doc_links(doc_embeddings)
                except Exception as exc:
                    logger.warning("Doc-link generation failed: %s", exc)
            duration_s = time.monotonic() - start_time

            # Rebuild the keyword index before any post-index deletes. A full
            # build inserts code_chunks with the FTS triggers suspended, so
            # until the rebuild the external-content index does not match the
            # table; a delete trigger in the stale sweep below would then fail
            # with "database disk image is malformed".
            if not incremental:
                if status_callback is not None:
                    status_callback("Rebuilding keyword index")
                self._metadata.set_fts_chunks(self._ensure_fts_parity(force=True))

            # Post-index stale sweep: a full re-index already covers the whole
            # tree, and incremental diffing removes working-tree orphans, so
            # the sweep only re-runs when the indexing policy changed (files
            # may have become excluded).
            if not incremental or self._indexing_policy_changed(
                root_path, include_tests, include_resources, res_exts, exclusion_patterns
            ):
                if status_callback is not None:
                    status_callback("Sweeping stale files")
                self._sweep_stale_files(root_path)

            # Incremental indexes rely on the triggers and rebuild only when
            # the keyword index has drifted; for full builds this is a cheap
            # parity check after the sweep.
            if status_callback is not None and incremental:
                status_callback("Verifying keyword index")
            fts_count = self._ensure_fts_parity()
            self._metadata.set_fts_chunks(fts_count)

            if status_callback is not None:
                status_callback("Persisting corpus statistics")
            try:
                corpus_chunks = self._rebuild_corpus_stats()
                self._metadata.set_int("corpus_chunk_count", corpus_chunks)
            except Exception as exc:
                logger.warning("Corpus statistics rebuild failed: %s", exc)

            # Interface dispatch: a receiver declared with an interface type
            # resolves to the interface method. Add the implementation
            # call targets before validation so paths and impact reach the code
            # that actually handles the call.
            try:
                derive_interface_dispatch_edges(self._db)
            except Exception as exc:
                logger.warning("Interface dispatch pass failed: %s", exc)

            # Post-index edge validation sweep: remove spurious self-edges,
            # same-name mis-resolutions, and out-of-range
            # attachments while preserving genuine recursive self-calls.
            if status_callback is not None:
                status_callback("Validating graph edges")
            try:
                self._edge_store.run_edge_validation_sweep()
            except Exception as exc:
                logger.warning("Edge validation sweep failed: %s", exc)

            # Derived trust passes: canonical names, TESTS edges, entry points,
            # importance, and degree counts. They run last because every one of
            # them depends on the final edge set.
            if status_callback is not None:
                status_callback("Computing graph trust passes")
            try:
                rebuild_derived_graph_data(self._db, root_path, self._settings)
            except Exception as exc:
                logger.warning("Derived graph passes failed: %s", exc)

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
            self._metadata.set("index_layout", self._settings.index_layout)
            self._metadata.set_int("skipped_large_files", len(oversized))
            self._metadata.set("graph_indexed", str(self._settings.index_graph).lower())
            self._metadata.set("index_include_tests", str(include_tests).lower())
            self._metadata.set("index_include_resources", str(include_resources).lower())
            self._metadata.set_json("index_resource_extensions", list(res_exts) if res_exts else [])
            self._metadata.set_json(
                "index_exclusion_patterns", sorted(exclusion_patterns) if exclusion_patterns else []
            )
            self._metadata.set("index_prose", str(self._settings.index_prose).lower())
            generation = self._compute_index_generation(root_path)
            try:
                self._persist_coverage(coverage_events, generation, processed_paths)
            except Exception as exc:
                logger.warning("Coverage persistence failed: %s", exc)
                self._metadata.set("index_generation", generation)
            self._metadata.set_int("index_format_version", INDEX_FORMAT_VERSION)
            self._metadata.set_index_status("ready")
            if status_callback is not None:
                status_callback("Optimizing index storage")
            self._db.run_post_index_maintenance(full_rebuild=not incremental)
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
            paths_count = conn.execute("SELECT COUNT(*) AS n FROM paths_fts;").fetchone()["n"]
        if code_count != fts_count or code_count != paths_count:
            logger.info(
                "FTS parity mismatch (code_chunks=%s, chunks_fts=%s, paths_fts=%s); rebuilding",
                code_count,
                fts_count,
                paths_count,
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

    def _insert_chunk(
        self,
        chunk: dict[str, Any],
        _source_bytes: bytes,
        conn: sqlite3.Connection | None = None,
        root_path: Path | None = None,
    ) -> int | None:
        """Insert a single chunk row, computing its subword tokens + checksum.

        Computes the ``subwords`` field (via ``identify_subwords``) and a
        content-derived ``tokens_checksum`` for dedup, then upserts into
        ``code_chunks`` (keyed on ``UNIQUE(file_path, line_start)``). FTS is
        kept in sync by the maintenance triggers — or rebuilt afterwards when a
        full build has suspended them.

        Args:
            chunk: The parsed chunk dict from the worker results.
            _source_bytes: Unused; retained for API compatibility.
            conn: An existing writer connection to reuse (no commit is issued);
                when ``None`` a fresh transaction is opened and committed.
            root_path: The repository root, used to store the FQN relative to
                it so the keyword scorer never sees the checkout location.

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
        is_test = 1 if _is_test_file(chunk.get("file_path", "")) else 0
        fqn_rel = _relative_fqn(chunk.get("fqn", ""), chunk.get("file_path", ""), root_path)
        path_rel = _relative_path(chunk.get("file_path", ""), root_path)
        if conn is not None:
            return self._insert_chunk_row(
                conn,
                chunk,
                content,
                subwords,
                declared_rules,
                tokens_hash,
                content_type,
                is_test,
                fqn_rel,
                path_rel,
            )
        with self._db.write_transaction() as owned:
            return self._insert_chunk_row(
                owned,
                chunk,
                content,
                subwords,
                declared_rules,
                tokens_hash,
                content_type,
                is_test,
                fqn_rel,
                path_rel,
            )

    def _insert_chunk_row(
        self,
        conn: sqlite3.Connection,
        chunk: dict[str, Any],
        content: str,
        subwords: str,
        declared_rules: str,
        tokens_hash: str,
        content_type: str,
        is_test: int = 0,
        fqn_rel: str = "",
        path_rel: str = "",
    ) -> int | None:
        """Upsert one ``code_chunks`` row over *conn* and return its row id."""
        try:
            cursor = conn.execute(
                "INSERT OR REPLACE INTO code_chunks "
                "(fqn, fqn_rel, path_rel, file_path, line_start, line_end, "
                "content, language, is_definition, chunk_type, "
                "chunk_node_type, subwords, declared_rules, tokens_checksum, "
                "content_type, is_test) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    chunk.get("fqn", ""),
                    fqn_rel,
                    path_rel,
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
                    is_test,
                ),
            )
            # chunks_fts is kept in sync by the FTS5 maintenance triggers; a
            # final rebuild_fts() guarantees parity after a full build batch.
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
            conn.execute("DELETE FROM symbols WHERE file_path = ?;", (file_path,))
            conn.execute("DELETE FROM file_checksums WHERE file_path = ?;", (file_path,))
            removed = len(chunk_ids) + len(sym_ids)
        return removed

    def _rebuild_corpus_stats(self) -> int:
        """Rebuild the persisted sub-word and prefix document frequencies.

        A full scan runs once per index build, never per query. Each token and
        3-character prefix is counted per ``(language, chunk)`` pair so a
        language-scoped lookup reads only the rows it needs.

        Returns:
            The number of chunks counted.
        """
        subword_counts: Counter[tuple[str, str]] = Counter()
        prefix_counts: Counter[tuple[str, str]] = Counter()
        with self._db.write_transaction() as conn:
            conn.execute("DELETE FROM subword_stats;")
            conn.execute("DELETE FROM prefix_stats;")
            rows = conn.execute("SELECT language, subwords FROM code_chunks;").fetchall()
            for row in rows:
                language = row["language"] or "unknown"
                tokens = set((row["subwords"] or "").split())
                prefixes = {token[:3] for token in tokens if len(token) >= 3}
                subword_counts.update((token, language) for token in tokens)
                prefix_counts.update((prefix, language) for prefix in prefixes)
            conn.executemany(
                "INSERT INTO subword_stats (token, language, doc_count) VALUES (?, ?, ?);",
                [(token, language, count) for (token, language), count in subword_counts.items()],
            )
            conn.executemany(
                "INSERT INTO prefix_stats (prefix, language, doc_count) VALUES (?, ?, ?);",
                [(prefix, language, count) for (prefix, language), count in prefix_counts.items()],
            )
        return len(rows)

    def _compute_index_generation(self, root_path: Path) -> str:
        """Return a stable digest identifying this published graph.

        The generation changes whenever the indexed content does, and is the
        cache/cursor key for later adjacency and paging layers. Including the
        finish timestamp keeps two identical rebuilds distinguishable while
        the table counts capture semantic changes.
        """
        with self._db.connect() as conn:
            rows = {
                table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()["n"])
                for table in ("symbols", "graph_edges", "code_chunks")
            }
            finished = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'last_indexed_at';"
            ).fetchone()
        payload = "|".join(
            [
                str(root_path.resolve()),
                finished["value"] if finished is not None else "",
                str(rows["symbols"]),
                str(rows["graph_edges"]),
                str(rows["code_chunks"]),
                str(SCHEMA_VERSION),
                str(INDEX_FORMAT_VERSION),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _persist_coverage(
        self,
        events: list[dict[str, Any]],
        generation: str,
        processed_paths: set[str],
    ) -> None:
        """Publish coverage rows and the index generation atomically.

        Coverage from the previous generation is superseded entirely. Rows for
        files that were not part of this run (incremental indexing) are carried
        forward, while rows for reprocessed files are replaced by the current
        events so a fixed file stops reporting a stale gap.

        Args:
            events: Coverage rows ``{file_path, kind, detail?, line_ranges?}``
                collected during discovery and parsing.
            generation: The generation digest to stamp on every row.
            processed_paths: Files whose source was parsed in this run; their
                previous coverage rows must not be carried forward.
        """
        current: dict[tuple[str, str], dict[str, Any]] = {}
        for event in events:
            key = (str(event["file_path"]), str(event["kind"]))
            current[key] = event
        event_paths = {file_path for file_path, _kind in current}

        with self._db.write_transaction() as conn:
            current_files = {
                str(row["file_path"])
                for row in conn.execute("SELECT file_path FROM file_checksums;")
            }
            carried: list[dict[str, Any]] = []
            for row in conn.execute(
                "SELECT file_path, kind, detail, line_ranges FROM index_coverage;"
            ):
                file_path = str(row["file_path"])
                if (
                    file_path in current_files
                    and file_path not in processed_paths
                    and file_path not in event_paths
                ):
                    carried.append(dict(row))
            conn.execute("DELETE FROM index_coverage;")
            conn.executemany(
                "INSERT OR REPLACE INTO index_coverage "
                "(file_path, kind, detail, line_ranges, generation) "
                "VALUES (?, ?, ?, ?, ?);",
                [
                    (
                        str(row["file_path"]),
                        str(row["kind"]),
                        str(row.get("detail") or ""),
                        row.get("line_ranges"),
                        generation,
                    )
                    for row in [*current.values(), *carried]
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO index_metadata (key, value) VALUES (?, ?);",
                ("index_generation", generation),
            )

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

    @staticmethod
    def _relative_module_path(file_path: str, root_path: Path) -> str:
        """Return *file_path* relative to *root_path* as a POSIX path."""
        try:
            return Path(file_path).resolve().relative_to(root_path.resolve()).as_posix()
        except (ValueError, OSError):
            return Path(file_path).as_posix()

    def _persist_doc_links(self, doc_embeddings: list[tuple[int, str, Any]]) -> None:
        """Create offline links from doc/config chunks to nearby code chunks.

        Two deterministic methods are combined:

        * ``embedding`` — the doc chunk's local embedding is searched against
          the code-only vector pool, keeping the top-k above the configured
          similarity floor;
        * ``symbol_mention`` — backticked or CamelCase identifiers in the doc
          chunk are resolved to exact indexed symbol names, then to their
          definition chunk.

        Args:
            doc_embeddings: ``(chunk_id, file_path, embedding)`` for each
                docs/config chunk embedded in this build.
        """
        if not doc_embeddings:
            return
        top_k = max(1, min(self._settings.doc_link_top_k, 10))
        floor = self._settings.doc_link_min_score
        cap = max(1, self._settings.doc_link_max_chunks)
        links: list[dict[str, Any]] = []
        for chunk_id, file_path, embedding in doc_embeddings[:cap]:
            for code_chunk_id, score in self._vector_index.search(
                embedding,
                top_k=top_k,
                content="code",
                exclude_file_paths={file_path},
            ):
                if score >= floor:
                    links.append(
                        {
                            "doc_chunk_id": chunk_id,
                            "code_chunk_id": code_chunk_id,
                            "score": round(float(score), 4),
                            "method": "embedding",
                        }
                    )

        with self._db.connect() as conn:
            doc_rows = conn.execute(
                "SELECT id, content FROM code_chunks "
                "WHERE content_type IN ('docs','config') ORDER BY id LIMIT ?;",
                (cap,),
            ).fetchall()
            for row in doc_rows:
                text = str(row["content"] or "")
                tokens = set(re.findall(r"`([^`]+)`", text))
                tokens.update(token for token in re.findall(r"\b[A-Z][a-z0-9]+[A-Z]\w*\b", text))
                for token in sorted(tokens)[:top_k]:
                    symbol = conn.execute(
                        "SELECT fqn FROM symbols WHERE name = ? LIMIT 1;", (token,)
                    ).fetchone()
                    if symbol is None:
                        continue
                    code = conn.execute(
                        "SELECT id FROM code_chunks WHERE fqn = ? "
                        "ORDER BY is_definition DESC, id LIMIT 1;",
                        (symbol["fqn"],),
                    ).fetchone()
                    if code is None:
                        continue
                    links.append(
                        {
                            "doc_chunk_id": int(row["id"]),
                            "code_chunk_id": int(code["id"]),
                            "score": 1.0,
                            "method": "symbol_mention",
                        }
                    )
        if links:
            self._doc_link_store.insert_batch(links)

    @staticmethod
    def _is_ts_source(file_path: str) -> bool:
        """Return whether *file_path* is a JavaScript/TypeScript source file."""
        return Path(file_path).suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

    @staticmethod
    def _ts_module_candidates(base: str) -> list[str]:
        """Return the index-relative paths a TS module specifier may resolve to.

        Covers explicit extensions, extension-less imports, a ``.js``
        specifier that points at a ``.ts`` source (ESM-style), and directory
        barrel ``index`` files.
        """
        normalized = posixpath.normpath(base)
        extensions = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs")
        candidates: list[str] = []
        if any(normalized.endswith(ext) for ext in extensions):
            candidates.append(normalized)
            stem = normalized.rsplit(".", 1)[0]
            candidates.extend(f"{stem}{ext}" for ext in extensions)
        else:
            candidates.extend(f"{normalized}{ext}" for ext in extensions)
            candidates.extend(f"{normalized}/index{ext}" for ext in extensions)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _resolve_ts_alias(
        specifier: str,
        base_dir: Path | None,
        paths: list[tuple[str, list[str]]],
    ) -> Path | None:
        """Resolve a non-relative TS import through ``baseUrl``/``paths``.

        Args:
            specifier: The bare module specifier (``@/components/Button``).
            base_dir: The ``baseUrl`` directory, or the repository root.
            paths: ``(pattern, targets)`` pairs from ``compilerOptions.paths``.

        Returns:
            The candidate absolute path, or ``None`` when the specifier is an
            external package.
        """
        for pattern, targets in paths:
            wildcard: str | None = None
            if "*" in pattern:
                prefix, suffix = pattern.split("*", 1)
                if not (specifier.startswith(prefix) and specifier.endswith(suffix)):
                    continue
                wildcard = specifier[len(prefix) : len(specifier) - len(suffix)]
            elif specifier != pattern:
                continue
            for target in targets:
                substituted = target.replace("*", wildcard or "")
                return (base_dir or Path()) / substituted
        if base_dir is not None:
            return base_dir / specifier
        return None

    @staticmethod
    def _load_tsconfig_aliases(root_path: Path) -> tuple[Path | None, list[tuple[str, list[str]]]]:
        """Read ``baseUrl``/``paths`` from the repository's tsconfig files.

        ``tsconfig.json`` is read first, then any ``tsconfig.*.json`` variants
        (Vite projects keep aliases in ``tsconfig.app.json``). Paths are
        resolved against ``baseUrl`` when present, otherwise the directory
        holding the tsconfig.

        Args:
            root_path: The indexed repository root.

        Returns:
            ``(base_dir, [(pattern, [target, ...]), ...])``; ``(None, [])``
            when no tsconfig carries path mappings.
        """
        config_files = [root_path / "tsconfig.json"]
        config_files.extend(
            p for p in sorted(root_path.glob("tsconfig.*.json")) if p.name != "tsconfig.json"
        )
        base_dir: Path | None = None
        paths: list[tuple[str, list[str]]] = []
        for config_file in config_files:
            if not config_file.exists():
                continue
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("Skipping unreadable %s: %s", config_file, exc)
                continue
            options = data.get("compilerOptions") or {}
            config_base = config_file.parent
            configured_base = options.get("baseUrl")
            resolved_base = (
                (config_base / str(configured_base)).resolve() if configured_base else config_base
            )
            configured_paths = options.get("paths") or {}
            if not configured_paths:
                continue
            if base_dir is None:
                base_dir = resolved_base
            for pattern, targets in configured_paths.items():
                if isinstance(targets, str):
                    targets = [targets]
                if not isinstance(targets, list):
                    continue
                paths.append((str(pattern), [str(target) for target in targets]))
        return base_dir, paths

    def _persist_module_edges(self, root_path: Path, import_edges: list[dict[str, Any]]) -> None:
        """Resolve import statements to file paths and persist ``module_edges``.

        Java imports resolve through the symbol catalog's ``conventional_fqn``;
        Python module imports resolve through a module-name index derived from
        the indexed file paths. Unresolved imports are retained with
        ``resolved = 0`` and their raw target so external dependencies stay
        visible without polluting the resolved graph.

        Args:
            root_path: Repository root used to make paths index-relative.
            import_edges: Raw ``IMPORTS`` edges emitted by the extractor.
        """
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT conventional_fqn, name, kind, file_path FROM symbols;"
            ).fetchall()
            indexed_files = conn.execute("SELECT DISTINCT file_path FROM code_chunks;").fetchall()

        conventional_files: dict[str, str] = {}
        type_files_by_name: dict[str, set[str]] = {}
        python_modules: dict[str, str] = {}
        all_files: set[str] = set()
        for indexed in indexed_files:
            if indexed["file_path"]:
                all_files.add(self._relative_module_path(str(indexed["file_path"]), root_path))
        for row in rows:
            file_path = str(row["file_path"])
            rel = self._relative_module_path(file_path, root_path)
            all_files.add(rel)
            conventional = row["conventional_fqn"]
            if conventional and conventional not in conventional_files:
                conventional_files[str(conventional)] = file_path
            if (row["kind"] or "") in _TYPE_DECLARATION_KINDS:
                type_files_by_name.setdefault(str(row["name"] or ""), set()).add(file_path)

        for rel in sorted(all_files):
            if not rel.endswith(".py"):
                continue
            parts = rel[: -len(".py")].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for start in range(len(parts)):
                module = ".".join(parts[start:])
                if module and module not in python_modules:
                    python_modules[module] = rel

        ts_base_dir, ts_paths = self._load_tsconfig_aliases(root_path)

        def resolve_ts_module(source_rel: str, raw: str) -> str | None:
            """Resolve a TypeScript import specifier to an index-relative file.

            Relative specifiers resolve against the importing file; aliases
            resolve through ``tsconfig`` ``baseUrl``/``paths``. Extension-less
            imports and directory imports resolve to ``.ts``/``.tsx``/
            ``.d.ts``/``.js``/``.jsx`` files and barrel ``index`` files.
            """
            specifier = raw.split("#", 1)[0]
            if not specifier:
                return None
            if specifier.startswith("."):
                base = Path(source_rel).parent / specifier
            elif specifier.startswith("/"):
                base = Path(specifier.lstrip("/"))
            else:
                alias_target = self._resolve_ts_alias(specifier, ts_base_dir, ts_paths)
                if alias_target is None:
                    return None
                try:
                    base = (
                        alias_target.relative_to(root_path)
                        if alias_target.is_absolute()
                        else alias_target
                    )
                except ValueError:
                    return None
            normalized = str(base)
            for candidate in self._ts_module_candidates(normalized):
                if candidate in all_files:
                    return candidate
            return None

        def resolve_target(raw: str) -> str | None:
            """Resolve one raw import target to an index-relative file path."""
            if raw in conventional_files:
                return self._relative_module_path(conventional_files[raw], root_path)
            if raw in python_modules:
                return python_modules[raw]
            if "." in raw:
                parent = raw.rsplit(".", 1)[0]
                if parent in python_modules:
                    return python_modules[parent]
            leaf = raw.rsplit(".", 1)[-1]
            candidates = type_files_by_name.get(leaf)
            if candidates and len(candidates) == 1:
                return self._relative_module_path(next(iter(candidates)), root_path)
            direct = raw.replace(".", "/") + ".py"
            if direct in all_files:
                return direct
            return None

        module_rows: list[dict[str, Any]] = []
        for edge in import_edges:
            source_path = edge.get("source_fqn") or ""
            if not source_path:
                continue
            source_rel = self._relative_module_path(source_path, root_path)
            raw = str(edge.get("target_fqn") or "")
            module_raw = str(edge.get("module") or raw)
            if self._is_ts_source(source_rel):
                target_path = resolve_ts_module(source_rel, module_raw)
                raw = module_raw
            else:
                target_path = resolve_target(raw) if raw else None
            module_rows.append(
                {
                    "source_path": source_rel,
                    "target_path": target_path,
                    "relation": "IMPORTS",
                    "target_raw": raw or None,
                    "resolved": 1 if target_path else 0,
                    "source_range": edge.get("source_range"),
                }
            )
        if module_rows:
            self._module_store.insert_edges_batch(module_rows)

    @staticmethod
    def _symbol_arity(fqn: str, language: str) -> int | None:
        """Return a symbol's parameter count, or ``None`` when it is unknown.

        Java/C#/Kotlin/Go/C++ declarations always encode their parameter list
        (a zero-argument method simply has no ``(...)`` suffix). TypeScript and
        Python method FQNs may omit parameters, so an absent list is unknown
        rather than zero and must not filter candidates.
        """
        if fqn.endswith(")"):
            start = fqn.rfind("(")
            if start != -1:
                inner = fqn[start + 1 : -1].strip()
                if not inner:
                    return 0
                count = 1
                depth = 0
                for char in inner:
                    if char in "<[(":
                        depth += 1
                    elif char in ">])":
                        depth = max(0, depth - 1)
                    elif char == "," and depth == 0:
                        count += 1
                return count
        if language in ("java", "c_sharp", "kotlin", "go", "cpp"):
            return 0
        return None

    @staticmethod
    def _symbol_kind(conn: Any, symbol_id: int, cache: dict[int, str]) -> str:
        """Return a symbol's kind, cached for the cross-file resolution batch."""
        kind = cache.get(symbol_id)
        if kind is None:
            row = conn.execute("SELECT kind FROM symbols WHERE id = ?;", (symbol_id,)).fetchone()
            kind = str(row["kind"]) if row is not None else ""
            cache[symbol_id] = kind
        return kind

    def _edge_properties(
        self,
        edge: dict[str, Any],
        tier: str | None,
        *,
        candidate_count: int = 1,
    ) -> dict[str, Any]:
        """Build the evidence object stored on a resolved or unresolved edge."""
        properties: dict[str, Any] = {"via": edge.get("via") or tier or "unknown"}
        line = self._declaration_line_from_range(edge.get("source_range"))
        if line is not None:
            properties["line"] = line
        if edge.get("arg_count") is not None:
            properties["arg_count"] = int(edge["arg_count"])
        if candidate_count > 1:
            properties["candidate_count"] = candidate_count
        return properties

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
        receiver_qualified: bool = False,
        arg_count: int | None = None,
        name_rows_cache: dict[str, list[Any]] | None = None,
        type_hierarchy: _TypeHierarchy | None = None,
    ) -> tuple[int | None, str | None, int]:
        """Resolve *symbol_fqn* against persisted symbols with evidence.

        Tier names match the persisted ``resolution_tier`` vocabulary:
        ``exact``, ``conventional``, ``same_file``, ``range``, ``fallback``,
        and ``ambiguous``. The third return value is the number of competing
        candidates. An ambiguous reference is never attached to the first
        same-named symbol: it returns ``(None, "ambiguous", n)`` so the caller
        can persist ``resolved = 0`` evidence.

        Args:
            conn: An open graph connection.
            symbol_fqn: The target name to resolve.
            source_fqn: FQN of the referencing symbol (for same-file/range tiers).
            source_range: Source range of the reference.
            type_only: When ``True`` the target names a type declaration (an
                inheritance base or an object creation), so a dotted
                import-map path that does not byte-match a symbol may fall back
                to the unique type sharing its leaf name.
            receiver_qualified: When ``True`` the raw target was a member
                expression (``repo.save``), so an unmatched receiver must not
                attach to a same-named method of another type. A dotted import
                path (``app.models.Article``) is not receiver-qualified.
            arg_count: Number of arguments at the call site. When several
                same-named overloads remain, candidates whose parameter count
                matches are preferred; no match leaves the reference ambiguous.
            name_rows_cache: Optional per-run cache of ``name -> symbol rows``.
                Candidate rows depend only on the leaf name, so reusing them
                avoids re-querying the same common names for every edge.
            type_hierarchy: Optional in-memory ancestry for the receiver's
                declared type. When the method is not declared on the type
                itself, it is looked up on the nearest supertype or interface;
                without it the inherited method stays unresolved.
        """
        if not symbol_fqn:
            return None, None, 0
        declaration = symbol_fqn.rsplit("::", 1)[-1] if "::" in symbol_fqn else symbol_fqn
        stripped_declaration = self._strip_params(declaration)
        simple = stripped_declaration.rsplit(".", 1)[-1]
        source_path = source_fqn.split("::", 1)[0] if source_fqn and "::" in source_fqn else ""
        call_line = self._declaration_line_from_range(source_range)
        stripped = self._strip_params(symbol_fqn)

        if name_rows_cache is not None and simple in name_rows_cache:
            rows = name_rows_cache[simple]
        else:
            rows = conn.execute(
                "SELECT s.id, s.fqn, s.conventional_fqn, s.file_path, s.line_start, s.line_end, "
                "s.kind, s.language, p.name AS parent_name "
                "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
                "WHERE s.name = ? ORDER BY s.id;",
                (simple,),
            ).fetchall()
            if name_rows_cache is not None:
                name_rows_cache[simple] = rows

        exact = [r for r in rows if r["fqn"] == symbol_fqn]
        if len(exact) == 1:
            return int(exact[0]["id"]), "exact", 1
        if len(exact) > 1:
            return None, "ambiguous", len(exact)

        if arg_count is not None and rows:
            known_arity: list[tuple[int, Any]] = []
            unknown_arity: list[Any] = []
            for row in rows:
                arity = self._symbol_arity(str(row["fqn"]), str(row["language"] or ""))
                if arity is None:
                    unknown_arity.append(row)
                else:
                    known_arity.append((arity, row))
            arity_matches = [row for arity, row in known_arity if arity == arg_count]
            if arity_matches:
                rows = [*arity_matches, *unknown_arity]

        conv = [
            r
            for r in rows
            if r["conventional_fqn"] and self._strip_params(r["conventional_fqn"]) == stripped
        ]
        if len(conv) == 1:
            return int(conv[0]["id"]), "conventional", 1
        if len(conv) > 1:
            return None, "ambiguous", len(conv)

        # Qualified-name tier: a dotted target like ``AuthService.authenticate``
        # names its enclosing class, so it must resolve to the symbol whose
        # parent class matches, NOT to a same-named method in the caller's file.
        class_part = None
        if "." in declaration:
            class_part = stripped_declaration.rsplit(".", 1)[0]
        class_leaf = class_part.rsplit(".", 1)[-1] if class_part else None
        if class_part:
            qualified = [
                r for r in rows if r["parent_name"] == class_part or r["parent_name"] == class_leaf
            ]
            if len(qualified) == 1:
                return int(qualified[0]["id"]), "conventional", 1
            if len(qualified) > 1:
                return None, "ambiguous", len(qualified)
            if receiver_qualified and type_hierarchy is not None:
                # The declared receiver type may inherit the method from a
                # superclass or implement it from an interface
                # (``extensionManager.getProxy()``). Walk the ancestry
                # nearest-first and attach only a unique declaration at the
                # closest level.
                for level in type_hierarchy.ancestor_name_levels(
                    class_part, class_leaf or "", source_path
                ):
                    inherited = [r for r in rows if r["parent_name"] in level]
                    if len(inherited) == 1:
                        return int(inherited[0]["id"]), "type_infer", 1
                    if len(inherited) > 1:
                        return None, "ambiguous", len(inherited)

        if class_part is not None and receiver_qualified:
            # A receiver-qualified call target (e.g. ``repository.save`` or
            # ``articleService.save``) must NEVER merge onto a same-named method
            # of a different receiver via the ``same_file``/``range``/``fallback``
            # tiers. Only a receiver whose enclosing type matches the callee's
            # may attach; an unknown receiver yields no edge, never a wrong one.
            same_qualified = [
                r
                for r in rows
                if source_path
                and r["file_path"] == source_path
                and (r["parent_name"] == class_part or r["parent_name"] == class_leaf)
            ]
            if len(same_qualified) == 1:
                return int(same_qualified[0]["id"]), "same_file", 1
            if len(same_qualified) > 1:
                return None, "ambiguous", len(same_qualified)
            if type_only:
                typed = [r for r in rows if (r["kind"] or "") in _TYPE_DECLARATION_KINDS]
                if len(typed) == 1:
                    return int(typed[0]["id"]), "fallback", 1
            return None, "ambiguous" if rows else None, len(rows)

        same_file = [r for r in rows if source_path and r["file_path"] == source_path]
        if len(same_file) == 1:
            return int(same_file[0]["id"]), "same_file", 1
        if len(same_file) > 1:
            return None, "ambiguous", len(same_file)

        if call_line is not None:
            decl = [
                r
                for r in rows
                if r["line_start"] is not None
                and r["line_end"] is not None
                and r["line_start"] <= call_line <= r["line_end"]
            ]
            if len(decl) == 1:
                return int(decl[0]["id"]), "range", 1
            if len(decl) > 1:
                return None, "ambiguous", len(decl)

        if len(rows) == 1:
            return int(rows[0]["id"]), "fallback", 1
        if type_only:
            typed = [r for r in rows if (r["kind"] or "") in _TYPE_DECLARATION_KINDS]
            if len(typed) == 1:
                return int(typed[0]["id"]), "fallback", 1
        if rows:
            logger.debug(
                "Dropping ambiguous cross-file symbol %r (%d candidates)",
                symbol_fqn,
                len(rows),
            )
        return None, "ambiguous" if rows else None, len(rows)
