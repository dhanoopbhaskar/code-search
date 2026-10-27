---
type: Module
title: "engine.graph_metrics"
description: "Read-only, deterministic graph-quality metrics: symbol and edge distributions, resolution tiers, unresolved targets, and coverage gaps for the current index generation."
resource: code_search/engine/graph_metrics.py
tags: [engine, graph, metrics, quality]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_metrics.py
    id: source-code
---

# Overview

The collector answers "how good is this graph before I ask it a structural
question?" — symbol counts by kind and language, edge totals split by type and
resolution tier, the most frequent unresolved raw targets, entry points by
reason, importance availability, and coverage rows grouped by kind, all scoped
to one `index_generation`.

It backs `code-search stats` and the graph-schema surface, so a consumer can
see the evidence limits of the index instead of inferring them from empty
results.

# Public API

- [`collect_graph_metrics`](../../functions/collect_graph_metrics.md) — the
  single entry point; `unresolved_limit` (default `_UNRESOLVED_TOP_LIMIT` = 20,
  clipped to 100) bounds the `unresolved_top` list.

# Properties

- **Read-only.** Nothing is written back to the index.
- **Deterministic.** Ordering and aggregation do not depend on row arrival.
- **Generation-scoped.** Every figure describes one published generation, so a
  concurrent reindex cannot produce a mixed picture.
