"""File watcher — polling-based change detection with debouncing.

Monitors a root directory for file modifications using SHA256 hashing and
fires a user-supplied callback after a configurable debounce window.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from src.engine.config import Settings

logger = logging.getLogger(__name__)

# Default directories excluded from watch scans.
_DEFAULT_EXCLUSIONS: set[str] = {".git", "node_modules", "__pycache__", ".context"}

# Chunk size (bytes) for streaming SHA256 computation.
_HASH_CHUNK_SIZE = 65536

# Thread join timeout when stopping the watcher.
_THREAD_JOIN_TIMEOUT = 5.0


class FileWatcher:
    """Polls the filesystem for changed files and invokes a callback.

    Uses SHA256 hashes to detect content changes. Accumulates changes
    within *debounce_seconds* before firing the ``on_change`` callback.
    """

    def __init__(
        self,
        root_path: Path,
        on_change: Callable[[list[Path]], None],
        debounce_seconds: float | None = None,
        exclusion_patterns: set[str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Create a file watcher rooted at *root_path*.

        Args:
            root_path: The directory to watch recursively.
            on_change: Callback invoked with the list of changed files once the
                debounce window elapses.
            debounce_seconds: Minimum quiet period before the callback fires;
                falls back to ``settings.watch_debounce_seconds`` when ``None``.
            exclusion_patterns: Directory/file-name parts to skip during scans;
                defaults to ``_DEFAULT_EXCLUSIONS`` when ``None``.
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted.
        """
        self._settings = settings or Settings.from_env()
        self._root_path = root_path
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds or self._settings.watch_debounce_seconds
        self._exclusion_patterns = exclusion_patterns or _DEFAULT_EXCLUSIONS
        self._running = False
        self._thread: threading.Thread | None = None
        self._file_hashes: dict[Path, str] = {}
        self._changed_files: list[Path] = []
        self._timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()

        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Snapshot the current hashes and begin the polling loop in a thread.

        Idempotent: if the watcher is already running, the call is a no-op.
        """
        if self._running:
            logger.warning("FileWatcher is already running")
            return
        self._running = True
        self._compute_initial_hashes()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="file-watcher")
        self._thread.start()
        logger.info("File watcher started for %s", self._root_path)

    def stop(self) -> None:
        """Stop the polling loop, cancel any pending timer, and join the thread."""
        self._running = False
        self._shutdown_event.set()
        with self._timer_lock:
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
                self._timer = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=_THREAD_JOIN_TIMEOUT)
        logger.info("File watcher stopped")

    def _compute_initial_hashes(self) -> None:
        """Hash every non-excluded file so only changes are reported later.

        Files that fail to hash (e.g. permission errors) are skipped.
        """
        self._file_hashes.clear()
        for file_path in self._root_path.rglob("*"):
            if self._should_exclude(file_path):
                continue
            if file_path.is_file():
                try:
                    self._file_hashes[file_path] = self._hash_file(file_path)
                except Exception:
                    continue

    def _should_exclude(self, path: Path) -> bool:
        """Return whether any part of *path* matches an exclusion pattern.

        Args:
            path: The path to test.

        Returns:
            ``True`` when any path component (e.g. ``".git"``) appears in the
            exclusion set.
        """
        return any(part in self._exclusion_patterns for part in path.parts)

    @staticmethod
    def _hash_file(file_path: Path) -> str:
        """Return a truncated SHA256 digest of *file_path*.

        Args:
            file_path: The file to hash, read in streaming chunks.

        Returns:
            The first 16 hex characters of the file's SHA256 digest.
        """
        hasher = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    def _poll_loop(self) -> None:
        """Poll the filesystem every ``watch_poll_interval`` seconds until stopped."""
        poll_interval = self._settings.watch_poll_interval
        while self._running and not self._shutdown_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.debug("Poll error: %s", exc)
            self._shutdown_event.wait(timeout=poll_interval)

    def _poll_once(self) -> None:
        """Scan the tree once, collecting files whose hash changed.

        New files (no prior hash) count as changed. Detected changes are
        passed to :meth:`_on_changes_detected` for debouncing.
        """
        changed: list[Path] = []
        for file_path in self._root_path.rglob("*"):
            if not self._running:
                return
            if self._should_exclude(file_path):
                continue
            if not file_path.is_file():
                continue

            try:
                current_hash = self._hash_file(file_path)
            except Exception:
                continue

            prev_hash = self._file_hashes.get(file_path)
            if prev_hash is None or prev_hash != current_hash:
                changed.append(file_path)

            self._file_hashes[file_path] = current_hash

        if changed:
            self._on_changes_detected(changed)

    def _on_changes_detected(self, changed: list[Path]) -> None:
        """Queue *changed* files and (re)arm the debounce timer.

        Each new batch resets the timer, so the callback only fires after the
        tree has been quiet for the full debounce window.

        Args:
            changed: The files detected as changed in the latest poll.
        """
        with self._timer_lock:
            self._changed_files.extend(changed)
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._fire_on_change)
            self._timer.daemon = True
            self._timer.start()

    def _fire_on_change(self) -> None:
        """Invoke the user callback with the queued changed files, then clear them."""
        with self._timer_lock:
            files = list(self._changed_files)
            self._changed_files.clear()
        if files:
            logger.debug("Detected %d changed files, firing callback", len(files))
            try:
                self._on_change(files)
            except Exception as exc:
                logger.error("File watcher callback error: %s", exc)


def create_watcher(
    root_path: Path,
    index_callback: Callable[[list[Path]], None],
    exclusion_patterns: set[str] | None = None,
    settings: Settings | None = None,
) -> FileWatcher:
    """Convenience factory for a ``FileWatcher`` with sensible defaults.

    Args:
        root_path: The directory to watch recursively.
        index_callback: Callback invoked with changed files after the debounce
            window; typically triggers an incremental reindex.
        exclusion_patterns: Directory/file-name parts to skip during scans.
        settings: Runtime settings; defaults to
            :func:`src.engine.config.Settings.from_env` when omitted.

    Returns:
        A configured :class:`FileWatcher` instance.
    """
    return FileWatcher(
        root_path=root_path,
        on_change=index_callback,
        exclusion_patterns=exclusion_patterns,
        settings=settings,
    )
