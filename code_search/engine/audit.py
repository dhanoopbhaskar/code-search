"""Append-only audit log for query tracking and compliance.

Records every search, symbol lookup, call graph, find_related, and
implementation-lookup query with timestamps, result counts, duration, and
redaction counts.
UPDATE and DELETE operations are blocked at the SQLite trigger level.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

AUDIT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS audit_log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    query_type TEXT NOT NULL
        CHECK(query_type IN ('search','get_symbol_definition','get_call_neighbors',
                             'find_related','get_implementations')),
    query_summary TEXT,
    result_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    redacted_count INTEGER NOT NULL DEFAULT 0
);
"""

AUDIT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log_entries(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log_entries(query_type);",
]

AUDIT_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_update
BEFORE UPDATE ON audit_log_entries
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries are append-only. UPDATE not allowed.');
END;
"""

AUDIT_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_delete
BEFORE DELETE ON audit_log_entries
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries are append-only. DELETE not allowed.');
END;
"""


class AuditDatabase:
    """Append-only SQLite database for query audit trail.

    Enforces immutability via SQLite triggers: once written, entries cannot
    be updated or deleted.
    """

    def __init__(self, db_path: Path) -> None:
        """Create an audit database backed by the file at *db_path*.

        Args:
            db_path: Filesystem path to the SQLite audit database file.
        """
        self._db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()

    @property
    def _conn(self) -> sqlite3.Connection:
        """The thread-local read connection, created lazily on first access."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return cast(sqlite3.Connection, self._local.conn)

    def _create_connection(self) -> sqlite3.Connection:
        """Open a new WAL-mode SQLite connection with row access enabled.

        Returns:
            A connection configured with ``journal_mode=WAL``, foreign keys
            enabled, and :class:`sqlite3.Row` row factory.
        """
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        """Create the audit table, indexes, and append-only triggers.

        Idempotent: uses ``CREATE TABLE IF NOT EXISTS`` and similar guarded
        DDL, so it is safe to call on every startup.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                self._migrate_query_type_check(conn)
                conn.execute(AUDIT_TABLE_DDL)
                for idx in AUDIT_INDEXES:
                    conn.execute(idx)
                conn.execute(AUDIT_APPEND_ONLY_TRIGGER)
                conn.execute(AUDIT_DELETE_TRIGGER)
                conn.commit()
            finally:
                conn.close()
            self._local.conn = None

    @staticmethod
    def _migrate_query_type_check(conn: sqlite3.Connection) -> None:
        """Rebuild a pre-existing audit table whose ``query_type`` CHECK predates
        the ``get_implementations`` query type, preserving every appended row.

        The audit schedule is append-only, so the table is renamed, recreated
        with the widened CHECK, repopulated verbatim, and the old copy dropped;
        the indexes and append-only triggers are recreated by :meth:`initialize`.
        """
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audit_log_entries';"
        ).fetchone()
        if row is None or "get_implementations" in (row["sql"] or ""):
            return
        conn.execute("DROP TRIGGER IF EXISTS trg_audit_append_only_update;")
        conn.execute("DROP TRIGGER IF EXISTS trg_audit_append_only_delete;")
        for idx in AUDIT_INDEXES:
            name = idx.split("idx_")[1].split(" ")[0]
            conn.execute(f"DROP INDEX IF EXISTS idx_{name};")
        conn.execute("ALTER TABLE audit_log_entries RENAME TO audit_log_entries_legacy;")
        conn.execute(AUDIT_TABLE_DDL)
        conn.execute(
            "INSERT INTO audit_log_entries "
            "(id, timestamp, query_type, query_summary, result_count, duration_ms, redacted_count) "
            "SELECT id, timestamp, query_type, query_summary, result_count, duration_ms, "
            "redacted_count FROM audit_log_entries_legacy;"
        )
        conn.execute("DROP TABLE audit_log_entries_legacy;")

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, Any, None]:
        """Context manager yielding the thread-local read connection.

        Yields:
            A live :class:`sqlite3.Connection` for read queries.
        """
        yield self._conn

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Connection, Any, None]:
        """Context manager yielding a dedicated connection for a write.

        Commits on clean exit and rolls back on any exception.

        Yields:
            A live :class:`sqlite3.Connection` for a single write transaction.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
                self._local.conn = None

    def write_entry(
        self,
        query_type: str,
        query_summary: str | None = None,
        result_count: int = 0,
        duration_ms: int = 0,
        redacted_count: int = 0,
    ) -> int:
        """Append an audit entry, returning its row ID.

        Args:
            query_type: One of ``"search"``, ``"get_symbol_definition"``,
                ``"get_call_neighbors"``, ``"find_related"``, or
                ``"get_implementations"``.
            query_summary: Optional human-readable summary of the query.
            result_count: Number of results returned to the caller.
            duration_ms: Query processing time in milliseconds.
            redacted_count: Number of values redacted while processing.

        Returns:
            The auto-incremented row ID of the inserted entry.

        Raises:
            ValueError: If *query_type* is not one of the allowed values.
        """
        valid_types = {
            "search",
            "get_symbol_definition",
            "get_call_neighbors",
            "find_related",
            "get_implementations",
        }
        if query_type not in valid_types:
            raise ValueError(f"Invalid query_type: {query_type}. Must be one of {valid_types}")
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.write_transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO audit_log_entries "
                "(timestamp, query_type, query_summary, result_count, duration_ms, redacted_count) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (timestamp, query_type, query_summary, result_count, duration_ms, redacted_count),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_entries(
        self,
        limit: int = 100,
        offset: int = 0,
        query_type: str | None = None,
    ) -> list[sqlite3.Row]:
        """Query audit entries, most recent first, optionally filtered by type.

        Args:
            limit: Maximum number of entries to return.
            offset: Number of newest entries to skip (for pagination).
            query_type: When set, only entries of this type are returned.

        Returns:
            A list of :class:`sqlite3.Row` objects ordered by row ID
            descending.
        """
        with self.connect() as conn:
            if query_type:
                rows = conn.execute(
                    "SELECT * FROM audit_log_entries "
                    "WHERE query_type = ? ORDER BY id DESC LIMIT ? OFFSET ?;",
                    (query_type, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log_entries ORDER BY id DESC LIMIT ? OFFSET ?;",
                    (limit, offset),
                ).fetchall()
            return rows

    def count_entries(self, query_type: str | None = None) -> int:
        """Count audit entries, optionally restricted to one *query_type*.

        Args:
            query_type: When set, only entries of this type are counted.

        Returns:
            The number of matching audit entries.
        """
        with self.connect() as conn:
            if query_type:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM audit_log_entries WHERE query_type = ?;",
                    (query_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as cnt FROM audit_log_entries;").fetchone()
            return row["cnt"] if row else 0

    def close(self) -> None:
        """Close the thread-local connection if one has been opened."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
