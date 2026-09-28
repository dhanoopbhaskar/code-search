"""In-memory latency and query metrics collector with percentile statistics.

Maintains a sliding window of query durations and tracks total redaction
counts. Used for health monitoring via the ``metrics`` CLI command.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any

from src.engine.config import Settings

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Sliding-window metrics collector for query latency and redaction counts.

    Computes P50 / P95 / P99 latency percentiles over the last *window_size*
    queries. The window is a fixed-size deque that evicts old entries.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Create a metrics collector backed by the given settings.

        Args:
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted. The
                sliding window size comes from
                ``settings.metrics_window_size``.
        """
        self._settings = settings or Settings.from_env()
        self._window_size = self._settings.metrics_window_size
        self._latencies: deque[float] = deque(maxlen=self._window_size)
        self._total_queries = 0
        self._total_redactions = 0
        self._lock = threading.Lock()

    def record_query(self, duration_ms: float) -> None:
        """Record a single query's latency and bump the total query count.

        Args:
            duration_ms: The query duration in milliseconds.
        """
        with self._lock:
            self._latencies.append(duration_ms)
            self._total_queries += 1

    def record_redaction(self, count: int) -> None:
        """Accumulate the number of redacted values for a query.

        Args:
            count: The number of redactions performed on a single query.
        """
        with self._lock:
            self._total_redactions += count

    @staticmethod
    def get_percentile(sorted_latencies: list[float], percentile: float) -> float:
        """Return the *percentile* value from a pre-sorted list of latencies.

        Args:
            sorted_latencies: Latency values in ascending order. Not mutated.
            percentile: The percentile to compute, in ``[0, 100]``.

        Returns:
            The latency value at the requested percentile, clamped to the last
            element, or ``0.0`` when the list is empty.
        """
        if not sorted_latencies:
            return 0.0
        idx = int(len(sorted_latencies) * percentile / 100.0)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]

    def get_latency_stats(self) -> dict[str, float]:
        """Compute P50 / P95 / P99 latency over the current sliding window.

        Returns:
            A mapping of percentile label to latency in milliseconds. All
            values are ``0.0`` when no queries have been recorded yet.
        """
        with self._lock:
            if not self._latencies:
                return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
            sorted_lats = sorted(self._latencies)
        return {
            "p50": self.get_percentile(sorted_lats, 50),
            "p95": self.get_percentile(sorted_lats, 95),
            "p99": self.get_percentile(sorted_lats, 99),
        }

    def get_total_queries(self) -> int:
        """Return the cumulative number of recorded queries."""
        return self._total_queries

    def get_total_redactions(self) -> int:
        """Return the cumulative number of recorded redactions."""
        return self._total_redactions

    def get_metrics_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all metrics for health reporting.

        Returns:
            A mapping with latency percentiles under ``"latency_ms"`` plus the
            cumulative ``"total_queries"`` and ``"total_redactions"`` counts.
        """
        latency = self.get_latency_stats()
        return {
            "latency_ms": latency,
            "total_queries": self._total_queries,
            "total_redactions": self._total_redactions,
        }

    def reset(self) -> None:
        """Clear the latency window and reset all counters to zero."""
        with self._lock:
            self._latencies.clear()
            self._total_queries = 0
            self._total_redactions = 0
