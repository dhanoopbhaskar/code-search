---
type: Class
title: "ArchitectureReport"
description: "Deterministic architecture overview of the indexed graph."
resource: code_search/engine/graph_query.py#ArchitectureReport
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Returned by [`GraphQueryService.architecture_report`](GraphQueryService.md);
rendered by
[`render_architecture_markdown`](../functions/render_architecture_markdown.md)
and written by [`cmd_map`](../functions/cmd_map.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `god_nodes` | `list[dict[str, Any]]` | Highest-degree resolved symbols; only function, method, class, interface, enum, and constructor kinds outside test files with degree above zero. |
| `communities` | `list[dict[str, Any]]` | Groups from deterministic label propagation over the resolved symbol graph. |
| `import_cycles` | `list[list[str]]` | Import cycles found by DFS over resolved `module_edges`. |
| `isolated` | `list[dict[str, Any]]` | Entity symbols with no resolved edge to another entity symbol, capped at `top_n`. |
| `edge_stats` | `dict[str, dict[str, int]]` | Per-edge-type counts from [`edge_resolution_stats`](../functions/edge_resolution_stats.md). |
| `suggested_questions` | `list[str]` | Follow-up questions derived from the report. |
| `stats` | `dict[str, Any]` | Aggregate counts such as `symbols` and `edges`. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return the structured report payload. |
