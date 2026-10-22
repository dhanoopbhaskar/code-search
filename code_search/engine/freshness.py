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
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_search.engine.config import Settings, _is_test_file
from code_search.engine.graph import GraphDatabase, IndexMetadataStore
from code_search.engine.parser import ASTParser

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
    "refreshing",
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
                :func:`code_search.engine.config.Settings.from_env` when omitted.
        """
        self._db = db
        self._metadata = metadata
        self._parser = parser
        self._context_dir = Path(context_dir)
        self._settings = settings or Settings.from_env()
        self._ttl = self._settings.freshness_ttl_seconds
        self._mode = self._settings.freshness_mode
        self._lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None

    def signal(self) -> dict[str, Any]:
        """Return the current freshness signal, TTL-cached per metadata.

        In ``blocking`` mode (the default) an expired cache is recomputed on
        the calling thread, preserving the existing behaviour. In
        ``deferred`` mode the last cached signal is served immediately and a
        background thread refreshes it, so a query never waits for the
        working-tree scan.
        """
        now = time.time()
        cached = self._metadata.get_json("freshness_signal")
        cached_at = self._metadata.get("freshness_checked_at")
        if self._mode == "deferred":
            if self._cache_valid(cached_at, now) and isinstance(cached, dict):
                result = dict(cached)
                result["refreshing"] = self._is_refreshing()
                return result
            self._start_background_refresh()
            if isinstance(cached, dict):
                result = dict(cached)
                result["refreshing"] = True
                return result
            pending = self._base_signal()
            pending["refreshing"] = True
            return pending
        with self._lock:
            if self._cache_valid(cached_at, now) and isinstance(cached, dict):
                return cached
            signal = self._compute()
            return self._store_signal(signal)

    def _cache_valid(self, cached_at: str | None, now: float) -> bool:
        """Return whether the cached signal is inside the effective TTL.

        The effective TTL scales with the last scan duration so a slow corpus
        is not rescanned faster than it can be served.
        """
        if self._ttl <= 0 or not cached_at:
            return False
        checked = _parse_iso(cached_at)
        if checked is None:
            return False
        effective = max(self._ttl, self._last_scan_duration() * 2.0)
        return (now - checked.timestamp()) < effective

    def _last_scan_duration(self) -> float:
        """Return the last full-scan duration in seconds (``0`` when unknown)."""
        raw = self._metadata.get("freshness_scan_duration_s")
        try:
            return float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _is_refreshing(self) -> bool:
        """Return whether a deferred background refresh is currently running."""
        thread = self._refresh_thread
        return thread is not None and thread.is_alive()

    def _start_background_refresh(self) -> None:
        """Start one background refresh when none is running."""
        with self._lock:
            if self._is_refreshing():
                return
            thread = threading.Thread(
                target=self._refresh_worker,
                name="code-search-freshness",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()

    def _refresh_worker(self) -> None:
        """Compute and store a freshness signal on a background thread."""
        try:
            started = time.monotonic()
            signal = self._compute()
            duration = time.monotonic() - started
            self._metadata.set("freshness_scan_duration_s", f"{duration:.3f}")
            self._store_signal(signal)
        except Exception:
            logger.warning("Background freshness refresh failed", exc_info=True)

    def _store_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Persist *signal* under the cache keys used by :meth:`signal`."""
        checked_at = _now_iso()
        stored = dict(signal)
        stored["checked_at"] = checked_at
        stored["refreshing"] = False
        self._metadata.set("freshness_checked_at", checked_at)
        self._metadata.set_json("freshness_signal", stored)
        return stored

    def mark_clean(self) -> None:
        """Seed a current (non-stale) cached signal after a successful index."""
        with self._lock:
            signal = self._base_signal()
            checked_at = _now_iso()
            signal["checked_at"] = checked_at
            self._metadata.set("freshness_checked_at", checked_at)
            self._metadata.set_json("freshness_signal", signal)
            head = self._git_head(self._index_root())
            if head:
                self._metadata.set("index_git_head", head)
            self._metadata.set("freshness_scan_duration_s", "0")

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
        A cheap git check short-circuits the scan when the indexed commit is
        unchanged and the working tree is clean.
        """
        status = self._metadata.get_index_status()
        if status != "ready":
            # Never lie about a non-ready lifecycle state: report it verbatim
            # with stale=false. Note "stale" here is the pre-existing
            # lifecycle value ("re-index recommended"), distinct from the
            # freshness boolean.
            return self._base_signal()

        if self._git_unchanged():
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

        head = self._git_head(self._index_root())
        if head:
            self._metadata.set("index_git_head", head)

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

    def _git_unchanged(self) -> bool:
        """Return whether git proves the working tree matches the index.

        The fast path requires both a stored indexed commit equal to the
        current ``HEAD`` and a clean (or untracked-free) ``git status``. Any
        failure or ambiguity falls through to the full scan.
        """
        root = self._index_root()
        stored = self._metadata.get("index_git_head")
        if not root or not stored:
            return False
        current = self._git_head(root)
        if not current or current != stored:
            return False
        try:
            proc = subprocess.run(
                ["git", "-C", root, "status", "--porcelain", "--untracked-files=no"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return False
        return proc.returncode == 0 and not proc.stdout.strip()

    @staticmethod
    def _git_head(root: str | None) -> str | None:
        """Return the repository's current commit, or ``None`` when unavailable."""
        if not root:
            return None
        try:
            proc = subprocess.run(
                ["git", "-C", root, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

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
