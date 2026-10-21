---
type: Class
title: "GraphAnswer"
description: "Result of a graph query: seeds, reachable nodes, edges, and outcome."
resource: code_search/engine/graph_query.py#GraphAnswer
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Returned by [`GraphQueryService.query`](GraphQueryService.md) and rendered by
[`render_query_text`](../functions/render_query_text.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `question` | `str` | The query text. |
| `seeds` | `list[GraphNode]` | Seed nodes the traversal started from. |
| `nodes` | `list[GraphNode]` | Nodes reached, seeds included. |
| `edges` | `list[GraphEdge]` | Edges between the returned nodes. |
| `truncated` | `bool` | Whether depth, node, fanout, or token limits trimmed the answer. |
| `outcome` | `str` | `resolved` (default) or `no_seed` when nothing mapped to a symbol. |
| `stats` | `dict[str, Any]` | Traversal statistics, including `collapsed_externals` when unresolved external leaves were removed. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return the structured (JSON) graph answer. |

See also [`GraphNode`](GraphNode.md) and [`GraphEdge`](GraphEdge.md).
