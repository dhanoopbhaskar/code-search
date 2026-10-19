---
type: Class
title: "PathAnswer"
description: "Result of a shortest-path request between two symbols."
resource: code_search/engine/graph_query.py#PathAnswer
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Returned by [`GraphQueryService.shortest_path`](GraphQueryService.md) and
rendered by [`render_path_text`](../functions/render_path_text.md). Ambiguous
endpoints are refused with ranked `candidates` rather than guessed. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `source` | `GraphNode \| None` | Resolved source node. |
| `target` | `GraphNode \| None` | Resolved target node. |
| `hops` | `list[GraphEdge]` | Edges along the path, in order. |
| `undirected` | `bool` | Whether edges were traversed in both directions. |
| `outcome` | `str` | `resolved` (default), `trivial` (same endpoint), `ambiguous`, `not_found`, or `no_path`. |
| `candidates` | `list[dict[str, Any]]` | Ranked candidates when an endpoint was ambiguous. |
| `explanation` | `str \| None` | Human-readable reason for a non-`resolved` outcome. |
| `stats` | `dict[str, Any]` | Traversal statistics. |

# Methods

| Method | Description |
|---|---|
| `found` (property) `-> bool` | Whether a path was found. |
| `as_dict() -> dict[str, Any]` | Return the structured (JSON) path answer. |
