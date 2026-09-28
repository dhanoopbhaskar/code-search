"""Server-side index change detection and reload.

Detects when the index has changed (via mtime tracking) and
triggers reload or returns a visible "index changed — restart required"
envelope.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from src.engine.index_metadata import IndexMetadata, IndexStatus

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
