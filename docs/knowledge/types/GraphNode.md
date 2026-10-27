---
type: Class
title: "GraphNode"
description: "Frozen dataclass for a symbol, file, or unresolved external node in a graph answer."
resource: code_search/engine/graph_query.py#GraphNode
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

A compact, immutable node returned in [`GraphAnswer`](GraphAnswer.md),
[`ExplainAnswer`](ExplainAnswer.md), [`ImpactAnswer`](ImpactAnswer.md), and
[`PathAnswer`](PathAnswer.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Stable node identifier used by edges: the FQN for symbols, `file:<path>` for file nodes. |
| `fqn` | `str` | Fully qualified name. |
| `name` | `str` | Short symbol name. |
| `kind` | `str` | Symbol kind. |
| `file_path` | `str \| None` | Declaring file; `None` for external leaves. |
| `line_start` | `int \| None` | First line of the declaration. |
| `line_end` | `int \| None` | Last line of the declaration. |
| `source` | `str` | Node origin: `symbol` (default), `file`, or `external` (unresolved leaf). |
| `distance` | `int` | Traversal distance from the nearest seed; defaults to `0`. |
| `signature` | `str \| None` | Declared signature, when known. |
| `docstring` | `str \| None` | Docstring, when known. |
| `reason` | `str \| None` | Provenance for seed nodes (for example `hybrid search hit #2 (score 0.812)`); `None` for nodes reached by traversal. |
| `symbol_id` | `int \| None` | Row id in the `symbols` table, populated on symbol nodes so adjacency-cache lookups can skip a per-node FQN query; `None` for file nodes and unresolved external leaves. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return a JSON-serialisable node payload. |
