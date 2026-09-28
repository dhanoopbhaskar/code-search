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
[`engine.metrics`](/modules/engine/metrics.md); surfaced by the `metrics`
CLI command.

# Methods

| Method | Description |
|---|---|
| `__init__(self, window_size: int = 1000) -> None` | Initialize a collector retaining the most recent *window_size* samples. |
| `record(self, duration_ms: float, redaction_count: int = 0) -> None` | Record a single query's duration and redaction count. |
| `percentiles() -> dict[str, float]` | Return `{p50, p95, p99}` latency percentiles over the current window. |
