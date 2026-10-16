"""Path normalization and stored-path resolution for ``find_related``.

Fixes the input boundary of the ``find_related`` MCP tool: a caller-supplied
``file_path`` may be absolute or project-relative, and must resolve to the
same indexed location (the stored ``code_chunks.file_path`` spelling) that the
indexer wrote. All functions are pure and stdlib-only (``pathlib``/``os``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

IndexConnection = sqlite3.Connection


def normalize_indexed_path(path: str, index_root: Path) -> Path | None:
    """Resolve *path* against the indexed repo *index_root*.

    Absolute paths are kept; relative paths are joined to *index_root* (never
    the caller's CWD). ``.``/``..`` segments and symlinks are collapsed via
    ``Path.resolve()``. Returns ``None`` when the resolved path escapes the
    index root — the caller treats that as the normal not-found outcome, never
    an error.
    """
    index_root_resolved = index_root.resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (index_root_resolved / candidate).resolve()
    if not _is_within(resolved, index_root_resolved):
        return None
    return resolved


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
