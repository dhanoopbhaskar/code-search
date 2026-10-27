---
type: Function
title: "collect_graph_metrics"
description: "Return symbol, edge, and coverage metrics for the current index."
resource: code_search/engine/graph_metrics.py#collect_graph_metrics
tags: [engine, function, graph_metrics]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_metrics.py
    id: source-code
---

# Overview

Return symbol, edge, and coverage metrics for the current index.

Defined in [`engine.graph_metrics`](../modules/engine/graph_metrics.md).

# Signature

`def collect_graph_metrics(db: GraphDatabase, *, unresolved_limit: int = _UNRESOLVED_TOP_LIMIT) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `unresolved_limit` | Maximum unresolved raw targets to report (clipped to 100) in the `unresolved_top` list. |

# Returns

A JSON-serialisable dict with `index_generation`, the graph-semantic `index_format_version`, edge totals and per-type/tier breakdowns, the most frequent unresolved targets, symbol counts by kind and language, entry points by reason, importance availability, and coverage rows grouped by kind.
