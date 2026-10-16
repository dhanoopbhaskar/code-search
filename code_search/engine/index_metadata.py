"""Index metadata tracking for change detection.

Tracks index version, mtime, timestamp, and status to enable
server-side detection of index changes for reload or envelope display.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any


class IndexStatus(Enum):
    """Current index health status."""

    CURRENT = "current"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class IndexMetadata:
    """Metadata tracking for index change detection.

    Attributes:
        version: Schema version of the index, incremented on each
            ``code-search index --force`` operation.
        mtime: Modification time of the index files; used by server
            to detect changes.
        timestamp: UTC timestamp when the index was last built/updated.
        status: Current index health status.
    """

    def __init__(
        self,
        version: str = "1.0.0",
        mtime: datetime | None = None,
        timestamp: datetime | None = None,
        status: IndexStatus | None = None,
    ) -> None:
        self.version = version
        self.mtime = mtime or datetime.now(UTC)
        self.timestamp = timestamp or datetime.now(UTC)
        self.status = status or (
            IndexStatus.CURRENT if mtime is not None else IndexStatus.UNAVAILABLE
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary for SQLite storage."""
        return {
            "version": self.version,
            "mtime": self.mtime.isoformat() if self.mtime else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexMetadata:
        """Create IndexMetadata from dictionary."""
        mtime = None
        if data.get("mtime"):
            mtime = datetime.fromisoformat(data["mtime"])
        timestamp = None
        if data.get("timestamp"):
            timestamp = datetime.fromisoformat(data["timestamp"])
        status = IndexStatus(data["status"]) if data.get("status") else None
        return cls(
            version=data.get("version", "1.0.0"),
            mtime=mtime,
            timestamp=timestamp,
            status=status,
        )

    def check_for_changes(self, new_mtime: datetime) -> dict[str, Any]:
        """Check if the index has changed based on new mtime.

        Args:
            new_mtime: The new modification time to compare against.

        Returns:
            dict with keys:
            - has_changed (bool): Whether the index has changed
            - old_status: The previous status
            - new_status: The suggested new status
        """
        has_changed = self.mtime != new_mtime

        if has_changed:
            old_status = self.status
            # Index changed: transition to stale, then update
            new_status = IndexStatus.STALE
        else:
            old_status = self.status
            new_status = IndexStatus.CURRENT if self.status is IndexStatus.CURRENT else self.status

        return {
            "has_changed": has_changed,
            "old_status": old_status,
            "new_status": new_status,
        }

    def update_mtime(self, new_mtime: datetime) -> IndexMetadata:
        """Update the modification time and status.

        Args:
            new_mtime: The new modification time.

        Returns:
            Updated IndexMetadata instance.
        """
        self.mtime = new_mtime
        self.timestamp = datetime.now(UTC)
        # If we were stale and now have a new mtime, we can mark as current
        if self.status is IndexStatus.STALE:
            self.status = IndexStatus.CURRENT
        return self
