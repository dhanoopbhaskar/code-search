---
type: Class
title: "MetricsCollector"
description: "Sliding-window metrics collector computing latency percentiles and tracking redaction counts."
resource: src/engine/metrics.py#MetricsCollector
tags: [metrics, observability]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/metrics.py
    id: source-code
---

# Overview

Thread-safe, in-memory sliding-window metrics collector. Records
per-query durations and cumulative redaction counts, computing
P50/P95/P99 latency percentiles. Defined in
[`engine.metrics`](../modules/engine/metrics.md); surfaced by the `metrics`
CLI command.

# Methods

| Method | Description |
|---|---|
| `__init__(settings: Settings \| None = None) -> None` | Create a metrics collector backed by the given settings. |
| `record_query(duration_ms: float) -> None` | Record a single query's latency and bump the total query count. |
| `record_redaction(count: int) -> None` | Accumulate the number of redacted values for a query. |
| `get_percentile(sorted_latencies: list[float], percentile: float) -> float` | Return the *percentile* value from a pre-sorted list of latencies. |
| `get_latency_stats() -> dict[str, float]` | Compute P50 / P95 / P99 latency over the current sliding window. |
| `get_total_queries() -> int` | Return the cumulative number of recorded queries. |
| `get_total_redactions() -> int` | Return the cumulative number of recorded redactions. |
| `get_metrics_snapshot() -> dict[str, Any]` | Return a snapshot of all metrics for health reporting. |
| `reset() -> None` | Clear the latency window and reset all counters to zero. |
