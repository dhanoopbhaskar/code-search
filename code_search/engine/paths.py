"""Path normalization and stored-path resolution.

Fixes the input boundary of the ``find_related`` MCP tool: a caller-supplied
``file_path`` may be absolute or project-relative, and must resolve to the
same indexed location (the stored ``code_chunks.file_path`` spelling) that the
indexer wrote. Also derives the repo-relative spelling used wherever a ranking
signal must not see the checkout location. All functions are pure and
stdlib-only (``pathlib``/``os``).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

IndexConnection = sqlite3.Connection


def portable_path(path: str | Path) -> str:
    """Return *path* in POSIX spelling.

    Stored paths are ranked against, compared as substrings, embedded in FQNs,
    and matched by callers that assume ``/`` separators. Rendering through
    :meth:`pathlib.Path.as_posix` keeps one spelling on every platform instead
    of letting the host separator leak into the index.

    Args:
        path: A path, absolute or relative, as a string or ``Path``.

    Returns:
        The path with ``/`` separators. On POSIX this is the input unchanged.
    """
    if not path:
        return ""
    return Path(path).as_posix()


def repo_relative_path(path: str | Path, root: Path | None) -> str:
    """Return *path* relative to *root*, or unchanged when it lies outside it.

    Path-shape scoring signals (substring and segment matches on the stored
    path) must not observe the checkout location: a repository cloned into a
    directory named after a query term would otherwise floor every chunk's
    score. Callers pass the indexed root so those signals see the same
    repo-relative spelling wherever the checkout lives.

    Args:
        path: A stored path, usually absolute.
        root: The indexed repository root, or ``None`` when unknown.

    Returns:
        The POSIX-spelled relative path, or *path* unchanged when it is empty
        or does not sit inside *root*.
    """
    text = str(path or "")
    if not text or root is None:
        return text
    try:
        relative = os.path.relpath(text, root)
    except ValueError:
        return text
    if relative == "." or relative == ".." or relative.startswith(f"..{os.sep}"):
        return text
    return Path(relative).as_posix()


def normalize_indexed_path(path: str, index_root: Path) -> Path | None:
    """Resolve *path* against the indexed repo *index_root*.

    Absolute paths are kept; relative paths are joined to *index_root* (never
    the caller's CWD). ``.``/``..`` segments and symlinks are collapsed via
    ``Path.resolve()``. On a case-insensitive filesystem a case-variant input
    is rewritten to the on-disk spelling so it matches the stored path.
    Returns ``None`` when the resolved path escapes the index root — the
    caller treats that as the normal not-found outcome, never an error.
    """
    index_root_resolved = index_root.resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (index_root_resolved / candidate).resolve()
    if not _is_within(resolved, index_root_resolved):
        return None
    return _canonical_case(resolved)


def _canonical_case(path: Path) -> Path:
    """Return *path* spelled as the filesystem reports it.

    ``Path.resolve()`` collapses symlinks but preserves the case supplied by
    the caller, even on a case-insensitive filesystem. Walking the existing
    directory entries and replacing each component with its on-disk spelling
    makes a case-variant input (``src/authservice.java``) equal the indexed
    path (``src/AuthService.java``). Components absent from the filesystem
    are left untouched, and an ambiguous case-insensitive match (two entries
    differing only by case) keeps the caller's spelling.

    Args:
        path: An absolute, symlink-resolved path.

    Returns:
        The path with each resolvable component in its on-disk case.
    """
    if not path.is_absolute():
        return path
    parts = path.parts
    current = Path(parts[0])
    for part in parts[1:]:
        try:
            entries = [entry.name for entry in current.iterdir()]
        except OSError:
            return path
        if part in entries:
            current = current / part
            continue
        folded = part.casefold()
        matches = [entry for entry in entries if entry.casefold() == folded]
        current = current / (matches[0] if len(matches) == 1 else part)
    return current


def resolve_stored_path(candidate: Path, conn: IndexConnection) -> str | None:
    """Return the stored ``code_chunks.file_path`` spelling for *candidate*.

    Exact match against the stored spelling first; on a miss, walk the distinct
    stored paths comparing their resolved forms so symlink / case-differing
    spellings map back to the stored string. Returns ``None``
    when no indexed file matches — the caller falls through to the existing
    not-found outcome.
    """
    candidate_str = str(candidate)
    row = conn.execute(
        "SELECT DISTINCT file_path FROM code_chunks WHERE file_path = ? LIMIT 1;",
        (candidate_str,),
    ).fetchone()
    if row is not None:
        return _row_value(row, "file_path")

    rows = conn.execute("SELECT DISTINCT file_path FROM code_chunks;").fetchall()
    for r in rows:
        fp = _row_value(r, "file_path")
        if not fp:
            continue
        try:
            if Path(fp).resolve() == candidate:
                return fp
        except OSError:
            continue
    return None


def _is_within(candidate: Path, root: Path) -> bool:
    """Return whether *candidate* is inside the directory tree rooted at *root*.

    Args:
        candidate: The path to test; expected to already be resolved.
        root: The boundary directory; expected to already be resolved.

    Returns:
        ``True`` when *candidate* equals *root* or descends from it,
        ``False`` when it escapes the boundary (``..`` above the root).
    """
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _row_value(row: Any, key: str) -> str | None:
    """Read a column value from a sqlite3 row as ``str`` or ``None``.

    Handles both ``sqlite3.Row`` objects (indexed by column name) and plain
    tuples (falling back to the first column), so callers can pass either
    result shape interchangeably.

    Args:
        row: A ``sqlite3.Row`` or tuple returned by a query.
        key: The column name to read when *row* supports named lookup.

    Returns:
        The cell value stringified, or ``None`` when the cell is ``NULL``,
        the column is missing, or the row is empty.
    """
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = row[0] if len(row) > 0 else None
    return str(value) if value is not None else None
