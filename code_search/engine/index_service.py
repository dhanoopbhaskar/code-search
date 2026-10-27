"""Server-side index change detection and reload.

Detects when the index has changed (via mtime tracking) and
triggers reload or returns a visible "index changed — restart required"
envelope.
"""

from __future__ import annotations

import logging
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_search.engine.index_metadata import IndexMetadata, IndexStatus

logger = logging.getLogger(__name__)


def index_mtime(metadata_store: Any) -> datetime | None:
    """Return the index's last build time (``last_indexed_at``), or ``None``.

    The timestamp is written by the indexer on every build, so an out-of-band
    ``code-search index --force`` changes it and a long-running server can
    compare against the mtime it loaded.

    Args:
        metadata_store: The ``IndexMetadataStore`` exposing ``get``.

    Returns:
        The parsed build time, or ``None`` when unset/unparseable.
    """
    raw = metadata_store.get("last_indexed_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


class IndexChangeDetector:
    """Detects index changes and manages reload state.

    Responsibilities:
    - Track index metadata (version, mtime, status)
    - Detect when index files have changed
    - Decide whether to reload or return envelope
    """

    def __init__(self, metadata: IndexMetadata | None = None) -> None:
        self._metadata = metadata or IndexMetadata()
        self._reload_required = False

    @classmethod
    def from_metadata_store(cls, metadata_store: Any) -> IndexChangeDetector:
        """Build a detector seeded with the index state the process loaded.

        Args:
            metadata_store: The ``IndexMetadataStore`` whose
                ``last_indexed_at`` records the build the serving process
                started with.

        Returns:
            A detector whose ``metadata.mtime`` is the loaded index build
            time (or the current time when no index exists yet).
        """
        mtime = index_mtime(metadata_store)
        status = IndexStatus.CURRENT if mtime else IndexStatus.UNAVAILABLE
        return cls(metadata=IndexMetadata(mtime=mtime, status=status))

    @property
    def metadata(self) -> IndexMetadata:
        """Get current index metadata."""
        return self._metadata

    @metadata.setter
    def metadata(self, value: IndexMetadata) -> None:
        """Set index metadata."""
        self._metadata = value

    def detect_index_change(self, new_mtime: Any) -> dict[str, Any]:
        """Detect if the index has changed based on new mtime.

        Args:
            new_mtime: The new modification time (datetime or ISO string).

        Returns:
            dict with detection results:
            - has_changed (bool): Whether index changed
            - should_reload (bool): Whether a reload is needed
            - envelope (str | None): Envelope message if reload not possible
            - new_status (IndexStatus): Suggested new status
        """
        # Normalize mtime to datetime
        if isinstance(new_mtime, str):
            new_mtime = datetime.fromisoformat(new_mtime)

        if new_mtime is None:
            # No index build recorded yet — there is nothing to compare
            # against, so no change is detected.
            return {
                "has_changed": False,
                "should_reload": False,
                "envelope": None,
                "new_status": self._metadata.status,
            }

        detection = self._metadata.check_for_changes(new_mtime)

        has_changed = detection["has_changed"]
        old_status = detection["old_status"]
        new_status = detection["new_status"]

        # Determine if reload is needed
        should_reload = has_changed and new_status is not IndexStatus.UNAVAILABLE

        # Generate envelope if reload not possible
        envelope = None
        if has_changed and new_status is IndexStatus.STALE:
            envelope = "index changed — restart required"

        result: dict[str, Any] = {
            "has_changed": has_changed,
            "should_reload": should_reload,
            "envelope": envelope,
            "new_status": new_status,
        }

        if has_changed:
            logger.info(
                "Index change detected: old_status=%s, new_status=%s, envelope=%s",
                old_status,
                new_status,
                envelope,
            )

        return result

    def mark_reload_complete(self, metadata_store: Any | None = None) -> IndexMetadata:
        """Mark the reload as complete and update status.

        Args:
            metadata_store: Optional metadata store to also update with the
                new mtime. When provided, the store's ``last_indexed_at`` is
                updated to match the detector's new mtime.

        Returns:
            Updated IndexMetadata with CURRENT status.
        """
        self._metadata = self._metadata.update_mtime(datetime.now(UTC))
        if metadata_store is not None:
            metadata_store.set(
                "last_indexed_at",
                self._metadata.mtime.isoformat().replace("+00:00", "Z"),
            )
        return self._metadata


class LiveIndexUpdater:
    """Keep a long-running server's index current with the working tree.

    Wraps :class:`~code_search.engine.watcher.FileWatcher` so the daemon and the
    MCP server observe edits without a second foreground process. A change batch
    is debounced by the watcher, re-indexed incrementally with the discovery
    policy recorded at index time, and followed by an in-memory reload of the
    vector index and search caches. The orchestrator calls
    ``FreshnessChecker.mark_clean()`` at the end of every successful run, so the
    stale flag clears without waiting for the freshness TTL.

    Re-index runs are serialised: a batch that arrives while another run is in
    flight waits for it instead of starting a second writer.
    """

    def __init__(
        self,
        comps: dict[str, Any],
        root_path: Path | None = None,
        exclusion_patterns: set[str] | None = None,
    ) -> None:
        """Create an updater bound to an initialised component registry.

        Args:
            comps: The registry returned by ``_initialize_components``; it must
                carry ``metadata``, ``orchestrator``, ``vector_index``,
                ``search``, ``embedding_gen``, and ``settings``.
            root_path: Directory to watch; defaults to the recorded
                ``index_root`` and then the context directory's parent.
            exclusion_patterns: Extra path parts to skip; always combined with
                ``.context`` so the index never watches its own output.
        """
        from code_search.engine.watcher import create_watcher

        metadata = comps["metadata"]
        context_dir = Path(comps["context_dir"])
        recorded_root = metadata.get("index_root")
        self._root_path = Path(root_path or recorded_root or context_dir.parent).resolve()
        self._comps = comps
        self._lock = threading.RLock()
        self._exclusion_patterns = set(exclusion_patterns or ()) | {".context"}
        self._settings = comps["settings"]
        self._watcher = create_watcher(
            root_path=self._root_path,
            index_callback=self._on_change,
            exclusion_patterns=self._exclusion_patterns,
            settings=self._settings,
        )

    @property
    def root_path(self) -> Path:
        """Return the directory being watched."""
        return self._root_path

    def start(self) -> None:
        """Start polling for changes in a background thread."""
        self._watcher.start()

    def stop(self) -> None:
        """Stop polling and wait for the watcher thread to exit."""
        self._watcher.stop()

    def reindex_once(self) -> dict[str, Any] | None:
        """Run one incremental index with the recorded discovery policy.

        Returns:
            The orchestrator summary, or ``None`` when the run failed (the
            failure is logged and the previous index is left in place).
        """
        with self._lock:
            metadata = self._comps["metadata"]
            include_tests = metadata.get("index_include_tests") != "false"
            include_resources = metadata.get("index_include_resources") == "true"
            resource_extensions = tuple(metadata.get_json("index_resource_extensions") or [])
            recorded_exclusions = set(metadata.get_json("index_exclusion_patterns") or [])
            try:
                summary = self._comps["orchestrator"].index_codebase(
                    root_path=self._root_path,
                    force=False,
                    incremental=True,
                    verbose=False,
                    exclusion_patterns=recorded_exclusions | self._exclusion_patterns,
                    include_tests=include_tests,
                    include_resources=include_resources,
                    resource_extensions=resource_extensions or None,
                )
            except Exception as exc:
                logger.warning("Incremental re-index failed: %s", exc)
                return None
            self.reload()
            return dict(summary)

    def reload(self) -> None:
        """Reload vectors and drop caches so the next query sees the new index."""
        with self._lock:
            embedding_gen = self._comps.get("embedding_gen")
            vector_index = self._comps.get("vector_index")
            if vector_index is not None:
                try:
                    vector_index.load()
                except Exception as exc:
                    logger.warning("Vector index reload failed: %s", exc)
            search_engine = self._comps.get("search")
            if search_engine is not None:
                try:
                    search_engine.reset_caches()
                except Exception as exc:
                    logger.warning("Search cache reset failed: %s", exc)
                if embedding_gen is not None:
                    search_engine._embedding_generator = embedding_gen
            symbol_store = self._comps.get("symbol_store")
            invalidate = getattr(symbol_store, "invalidate_resolution_cache", None)
            if callable(invalidate):
                with suppress(Exception):
                    invalidate()
            detector = self._comps.get("index_change_detector")
            metadata = self._comps.get("metadata")
            if detector is not None and metadata is not None:
                try:
                    detector.mark_reload_complete(metadata)
                except Exception as exc:
                    logger.warning("Index-change detector update failed: %s", exc)

    def _on_change(self, files: list[Path]) -> None:
        """Re-index one debounced change batch.

        Args:
            files: The changed paths reported by the watcher. The incremental
                index discovers its own diff, so the list is only logged.
        """
        logger.info("Detected %d changed file(s); refreshing the index", len(files))
        summary = self.reindex_once()
        if summary is not None:
            logger.info(
                "Incremental re-index complete: %s files, %s symbols",
                summary.get("total_files"),
                summary.get("total_symbols"),
            )
