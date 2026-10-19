---
type: Class
title: "GraphEdge"
description: "Frozen dataclass for a directed, confidence-labelled relation between two graph-answer nodes."
resource: code_search/engine/graph_query.py#GraphEdge
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

A relation between two [`GraphNode`](GraphNode.md) keys, carrying the
confidence label from
[`resolve_confidence`](../functions/resolve_confidence.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `source` | `str` | Key of the stored-edge source node. |
| `target` | `str` | Key of the stored-edge target node. |
| `relation` | `str` | Edge type (`CALLS`, `INHERITS`, `IMPORTS`, `REFERENCES`, or `CONTAINS`). |
| `confidence` | `str` | `EXTRACTED`, `INFERRED`, `AMBIGUOUS`, or `UNRESOLVED`. |
| `direction` | `str` | `forward` (stored direction) or `reverse` (traversed backwards); defaults to `forward`. |
| `resolution_tier` | `str \| None` | Persisted resolution tier. |
| `target_raw` | `str \| None` | Unresolved target text, when the edge did not resolve. |
| `source_range` | `str \| None` | Source range of the reference. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return a JSON-serialisable edge payload. |
| `render() -> str` | Render the edge in its actual direction, flagging reverse traversal. |
