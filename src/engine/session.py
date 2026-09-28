"""Session database — tracks file READ/WRITE events for personalised ranking.

Each event gets a base weight (WRITE=1.0, READ=0.7) that decays
exponentially over time. Recently accessed files receive a boost during
reranking via ``get_weights_for_files()``.
"""

from __future__ import annotations

import math
import sqlite3
import threading
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from src.engine.config import Settings

SESSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('READ', 'WRITE')),
    event_time TEXT NOT NULL,
    weight_score REAL NOT NULL CHECK(weight_score >= 0.0 AND weight_score <= 1.0),
    ttl_expires_at TEXT NOT NULL,
    CHECK(ttl_expires_at > event_time)
);
"""

SESSION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_session_file ON sessions(file_path);",
    "CREATE INDEX IF NOT EXISTS idx_session_time ON sessions(event_time);",
    "CREATE INDEX IF NOT EXISTS idx_session_expiry ON sessions(ttl_expires_at);",
    "CREATE INDEX IF NOT EXISTS idx_session_id ON sessions(session_id);",
]

WEIGHT_CLEANUP_DDL = """
CREATE TRIGGER IF NOT EXISTS trg_session_cleanup_expired
AFTER INSERT ON sessions
BEGIN
    DELETE FROM sessions WHERE ttl_expires_at < strftime('%Y-%m-%dT%H:%M:%fZ','now');
END;
"""


class SessionDatabase:
    """Tracks code navigation events to enable session-based personalised reranking.

    Each ``READ`` or ``WRITE`` event is stored with a base weight and TTL.
    Weight decays exponentially: ``w(t) = w0 * exp(-lambda * delta_hours)``.
    """

    def __init__(self, db_path: Path, settings: Settings | None = None) -> None:
        """Create a session database backed by the file at *db_path*.

        Args:
            db_path: Filesystem path to the SQLite session database file.
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted.
        """
        self._db_path = db_path
        self._settings = settings or Settings.from_env()
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
        """Create the sessions table, indexes, and expired-row cleanup trigger.

        Idempotent: uses guarded ``CREATE ... IF NOT EXISTS`` DDL, safe to
        call on every startup.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                conn.execute(SESSION_TABLE_DDL)
                for idx in SESSION_INDEXES:
                    conn.execute(idx)
                conn.execute(WEIGHT_CLEANUP_DDL)
                conn.commit()
            finally:
                conn.close()
            self._local.conn = None

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

    def record_event(
        self,
        file_path: str,
        event_type: str,
        session_id: str | None = None,
    ) -> str:
        """Record a READ or WRITE event, returning the session ID.

        The event is stored with a base weight (WRITE=``session_write_weight``,
        READ=``session_read_weight``) and a TTL of ``session_ttl_hours``.

        Args:
            file_path: The stored path of the file the event refers to.
            event_type: ``"READ"`` or ``"WRITE"``.
            session_id: Optional session ID; a fresh UUID is generated when
                omitted and returned.

        Returns:
            The session ID the event was recorded under.

        Raises:
            ValueError: If *event_type* is not ``"READ"`` or ``"WRITE"``.
        """
        if event_type not in ("READ", "WRITE"):
            raise ValueError("event_type must be READ or WRITE")
        sid = session_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        event_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        ttl_hours = self._settings.session_ttl_hours
        from datetime import timedelta

        expires = now + timedelta(hours=ttl_hours)
        ttl_expires_at = expires.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        w0 = (
            self._settings.session_write_weight
            if event_type == "WRITE"
            else self._settings.session_read_weight
        )

        with self.write_transaction() as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(session_id, file_path, event_type, event_time, weight_score, ttl_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (sid, file_path, event_type, event_time, w0, ttl_expires_at),
            )
        return sid

    def get_active_sessions(self) -> list[sqlite3.Row]:
        """Return all session rows, newest first, after purging expired ones.

        Returns:
            A list of :class:`sqlite3.Row` objects ordered by event time
            descending.
        """
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE ttl_expires_at < ?;", (now,))
            rows = conn.execute(
                "SELECT session_id, file_path, event_type, weight_score, event_time "
                "FROM sessions ORDER BY event_time DESC;"
            ).fetchall()
            return rows

    def get_weights_for_files(self, file_paths: list[str]) -> list[dict[str, Any]]:
        """Compute decayed session weights for the given file paths.

        Returns a list of ``{file_path, weight_score}`` dicts with the best
        (highest) decayed weight per file. The expired-row cleanup DELETE is a
        write and is committed inside a write transaction so the thread-local
        connection never holds an open write lock (which would make concurrent
        daemon handlers hit ``database is locked``).

        Args:
            file_paths: The stored file paths to compute weights for.

        Returns:
            A list of ``{"file_path": ..., "weight_score": ...}`` dicts, one
            per file with at least one matching (possibly path-suffixed)
            session row.
        """
        if not file_paths:
            return []
        now = datetime.now(UTC)
        lam = self._settings.decay_constant
        with self.write_transaction() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE ttl_expires_at < ?;",
                (now.strftime("%Y-%m-%dT%H:%M:%fZ"),),
            )
            rows = conn.execute(
                "SELECT file_path, weight_score, event_time FROM sessions ORDER BY event_time DESC;"
            ).fetchall()

        best: dict[str, float] = {}
        for target_fp in file_paths:
            for row in rows:
                sess_fp = row["file_path"]
                if (
                    target_fp == sess_fp
                    or target_fp.endswith("/" + sess_fp)
                    or sess_fp.endswith("/" + target_fp)
                ):
                    w0 = float(row["weight_score"])
                    event_time = datetime.fromisoformat(row["event_time"])
                    delta_hours = (now - event_time).total_seconds() / 3600.0
                    decayed = w0 * math.exp(-lam * delta_hours)
                    if target_fp not in best or decayed > best[target_fp]:
                        best[target_fp] = decayed

        return [{"file_path": fp, "weight_score": w} for fp, w in best.items()]

    def track_git_changes(self, repo_path: Path) -> int:
        """Run ``git status --porcelain`` and record WRITE events for modified files.

        Args:
            repo_path: The repository root to scan.

        Returns:
            The number of modified files that were recorded as WRITE events.
        """
        modified = self._detect_git_modified(repo_path)
        import contextlib

        for fp in modified:
            with contextlib.suppress(Exception):
                self.record_event(str(fp), "WRITE")
        return len(modified)

    @staticmethod
    def _detect_git_modified(repo_path: Path) -> list[Path]:
        """List files that are modified, added, or untracked in the repository.

        Args:
            repo_path: The repository root to query.

        Returns:
            The resolved paths of files whose ``git status --porcelain`` entry
            marks them as modified (``M``), added (``A``), or untracked (``?``);
            empty when ``git`` fails or is unavailable.
        """
        try:
            import subprocess

            result = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            modified: list[Path] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                status = line[:2]
                file_path_str = line[3:]
                if "M" in status or "?" in status or "A" in status:
                    full_path = (repo_path / file_path_str).resolve()
                    if full_path.is_file():
                        modified.append(full_path)
            return modified
        except Exception:
            return []

    def close(self) -> None:
        """Close the thread-local connection if one has been opened."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
