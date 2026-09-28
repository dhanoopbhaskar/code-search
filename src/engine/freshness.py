"""Index-freshness signal computation.

The freshness signal answers "is the working tree ahead of the index?" via a
two-tier detection built on the schema-v8 stat baselines:

1. **Stat fast-path** — files whose stored ``size``/``file_mtime_ns`` match the
   current ``os.stat`` result are skipped without re-hashing.
2. **Re-hash on stat change** — a stat mismatch triggers a sha256 comparison
   against the stored content checksum. A matching hash (mtime-only touch)
   self-heals the baseline instead of double-counting; a differing hash is a
   modified file.

Deleted files are caught by stat failure; new files are found by a discovery
walk using the stored discovery configuration. The signal is TTL-cached under
``index_metadata`` (``freshness_checked_at`` / ``freshness_signal``) so steady
queries pay a single metadata read, and ``mark_clean()`` seeds a current
signal right after a successful index so the first post-index query never
pays a scan.
"""

import hashlib
import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.engine.config import Settings, _is_test_file
from src.engine.graph import GraphDatabase, IndexMetadataStore
from src.engine.parser import ASTParser

logger = logging.getLogger(__name__)

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

FRESHNESS_KEYS = (
    "stale",
    "stale_change_count",
    "modified_files",
    "deleted_files",
    "new_files",
    "index_age_s",
    "index_status",
    "index_root",
    "checked_at",
)


def _now_iso() -> str:
    """Return the current UTC time formatted as an ISO timestamp string.

    Uses the module-global :data:`_ISO_FORMAT` pattern, which mirrors the
    timestamps stored by the metadata store so cached freshness values round-trip
    cleanly.

    Returns:
        The current time in ``%Y-%m-%dT%H:%M:%S.%fZ`` form.
    """
    return datetime.now(UTC).strftime(_ISO_FORMAT)


def _parse_iso(raw: str) -> datetime | None:
    """Parse an ISO timestamp string into a timezone-aware datetime.

    Accepts trailing ``Z`` (the form produced by :func:`_now_iso`) by normalising
    it to an explicit UTC offset before parsing.

    Args:
        raw: The ISO timestamp string to parse.

    Returns:
        The parsed datetime, or ``None`` when *raw* is not a valid ISO
        timestamp.
    """
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class FreshnessChecker:
    """Computes a working-tree-vs-index staleness signal."""

    def __init__(
        self,
        db: GraphDatabase,
        metadata: IndexMetadataStore,
        parser: ASTParser,
        context_dir: Path,
        settings: Settings | None = None,
    ) -> None:
        """Create a freshness checker for *context_dir*.

        Args:
            db: The graph database holding the stat baselines.
            metadata: The index metadata store used for caching and lifecycle
                state.
            parser: The parser used for new-file discovery walks.
            context_dir: The daemon's context directory (``.context/``);
                ``index_root`` defaults to its parent.
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted.
        """
        self._db = db
        self._metadata = metadata
        self._parser = parser
        self._context_dir = Path(context_dir)
        self._settings = settings or Settings.from_env()
        self._ttl = self._settings.freshness_ttl_seconds
        self._lock = threading.Lock()

    def signal(self) -> dict[str, Any]:
        """Return the current freshness signal, TTL-cached per metadata."""
        now = time.time()
        with self._lock:
            cached_at = self._metadata.get("freshness_checked_at")
            if self._ttl > 0 and cached_at:
                checked = _parse_iso(cached_at)
                if checked is not None and (now - checked.timestamp()) < self._ttl:
                    cached = self._metadata.get_json("freshness_signal")
                    if isinstance(cached, dict):
                        return cached
            signal = self._compute()
            checked_at = _now_iso()
            signal["checked_at"] = checked_at
            self._metadata.set("freshness_checked_at", checked_at)
            self._metadata.set_json("freshness_signal", signal)
            return signal

    def mark_clean(self) -> None:
        """Seed a current (non-stale) cached signal after a successful index."""
        with self._lock:
            signal = self._base_signal()
            checked_at = _now_iso()
            signal["checked_at"] = checked_at
            self._metadata.set("freshness_checked_at", checked_at)
            self._metadata.set_json("freshness_signal", signal)

    def _base_signal(self) -> dict[str, Any]:
        """Build a fresh, non-stale signal from current metadata state."""
        return {
            "stale": False,
            "stale_change_count": 0,
            "modified_files": 0,
            "deleted_files": 0,
            "new_files": 0,
            "index_age_s": self._index_age_s(),
            "index_status": self._metadata.get_index_status() or "unindexed",
            "index_root": self._index_root(),
            "checked_at": _now_iso(),
        }

    def _index_root(self) -> str | None:
        """Return the stored index root, or ``context_dir``'s parent.

        Returns:
            The stored ``index_root`` metadata value when present, otherwise
            the parent of the checker's context directory.
        """
        stored = self._metadata.get("index_root")
        if stored:
            return stored
        return str(self._context_dir.parent)

    def _index_age_s(self) -> float | None:
        """Return seconds since the last index, or ``None`` when unknown.

        Returns:
            The non-negative age of the index in seconds, or ``None`` when no
            ``last_indexed_at`` timestamp is stored or it cannot be parsed.
        """
        last = self._metadata.get("last_indexed_at")
        if not last:
            return None
        parsed = _parse_iso(last)
        if parsed is None:
            return None
        return max(0.0, time.time() - parsed.timestamp())

    def _compute(self) -> dict[str, Any]:
        """Scan the working tree against baselines and build a signal.

        Uses the stat fast-path, re-hashing on stat mismatch, and heals
        mtime-only touches. Returns a non-stale signal (reporting the lifecycle
        status verbatim) when the index is not ``ready``; otherwise classifies
        files as modified, deleted, or new and reports ``stale`` accordingly.
        """
        status = self._metadata.get_index_status()
        if status != "ready":
            # Never lie about a non-ready lifecycle state: report it verbatim
            # with stale=false. Note "stale" here is the pre-existing
            # lifecycle value ("re-index recommended"), distinct from the
            # freshness boolean.
            return self._base_signal()

        modified = 0
        deleted = 0
        heals: list[tuple[int, int, str]] = []
        indexed_paths: set[str] = set()

        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT file_path, checksum, size, file_mtime_ns FROM file_checksums;"
            ).fetchall()
            for row in rows:
                path_str = row["file_path"]
                if not path_str:
                    continue
                indexed_paths.add(str(Path(path_str).resolve()))
                st = self._stat(path_str)
                if st is None:
                    deleted += 1
                    continue
                stored_size = row["size"]
                stored_mtime = row["file_mtime_ns"]
                if (
                    stored_size is not None
                    and stored_mtime is not None
                    and st.st_size == stored_size
                    and st.st_mtime_ns == stored_mtime
                ):
                    continue
                content = self._read_bytes(path_str)
                if content is None:
                    deleted += 1
                    continue
                if hashlib.sha256(content).hexdigest() == row["checksum"]:
                    heals.append((st.st_size, st.st_mtime_ns, path_str))
                else:
                    modified += 1

        if heals:
            try:
                with self._db.write_transaction() as wconn:
                    wconn.executemany(
                        "UPDATE file_checksums SET size = ?, file_mtime_ns = ? "
                        "WHERE file_path = ?;",
                        heals,
                    )
            except sqlite3.Error:
                logger.warning("Freshness baseline self-heal failed", exc_info=True)

        new_files = self._count_new_files(indexed_paths)
        total = modified + deleted + new_files

        signal = self._base_signal()
        signal.update(
            {
                "stale": total > 0,
                "stale_change_count": total,
                "modified_files": modified,
                "deleted_files": deleted,
                "new_files": new_files,
            }
        )
        return signal

    def _count_new_files(self, indexed_paths: set[str]) -> int:
        """Count discoverable files not present in the indexed set.

        Re-runs the parser's discovery walk with the stored configuration from
        index time, applying the stored test-file filter, and counts files
        whose resolved path is absent from *indexed_paths*.

        Args:
            indexed_paths: Resolved file paths already covered by the index.

        Returns:
            The number of discovered files missing from the index, or ``0``
            when discovery fails or the root directory is missing.
        """
        root = self._index_root()
        index_root = Path(root) if root else self._context_dir.parent
        if not index_root.is_dir():
            return 0
        exclusion_patterns = set(self._metadata.get_json("index_exclusion_patterns") or [])
        include_resources = self._metadata.get("index_include_resources") == "true"
        resource_extensions = tuple(self._metadata.get_json("index_resource_extensions") or [])
        include_tests = self._metadata.get("index_include_tests") != "false"
        index_prose = self._metadata.get("index_prose") == "true"
        try:
            discovered = self._parser.discover_files(
                index_root,
                exclusion_patterns=exclusion_patterns,
                include_resources=include_resources,
                resource_extensions=resource_extensions or None,
                index_prose=index_prose,
            )
        except Exception:
            logger.warning("Freshness discovery walk failed", exc_info=True)
            return 0
        if not include_tests:
            discovered = [f for f in discovered if not _is_test_file(f)]
        return sum(1 for f in discovered if str(f.resolve()) not in indexed_paths)

    @staticmethod
    def _stat(path: str) -> Any:
        """Return ``os.stat`` results for *path*, or ``None`` on ``OSError``.

        Args:
            path: Filesystem path to stat.

        Returns:
            The stat result, or ``None`` when the path cannot be stat'd
            (typically a deleted file).
        """
        try:
            return Path(path).stat()
        except OSError:
            return None

    @staticmethod
    def _read_bytes(path: str) -> bytes | None:
        """Read the full contents of *path*, or ``None`` on ``OSError``.

        Args:
            path: Filesystem path to read.

        Returns:
            The file bytes, or ``None`` when the file cannot be read.
        """
        try:
            return Path(path).read_bytes()
        except OSError:
            return None
