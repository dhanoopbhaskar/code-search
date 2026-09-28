---
type: Module
title: "engine.metrics"
description: "In-memory latency and query metrics collector with thread-safe sliding-window percentile statistics."
resource: src/engine/metrics.py
tags: [engine, metrics, observability]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/metrics.py
    id: source-code
---

# Overview

In-memory latency and query metrics collector with thread-safe
sliding-window statistics. Maintains per-query durations and cumulative
redaction counts, computing P50/P95/P99 percentiles for health monitoring
via the `metrics` CLI command.

# Key Classes

- [`MetricsCollector`](/types/MetricsCollector.md) — sliding-window metrics collector computing latency percentiles and tracking redaction counts.
