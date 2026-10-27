---
type: Class
title: "ExplainAnswer"
description: "Result of an explain request: a symbol's ego graph, rationale comments, and linked docs."
resource: code_search/engine/graph_query.py#ExplainAnswer
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Returned by [`GraphQueryService.explain`](GraphQueryService.md) and rendered by
[`render_explain_text`](../functions/render_explain_text.md). Rationale rows
come from [`RationaleStore`](RationaleStore.md) and linked docs from
[`DocLinkStore`](DocLinkStore.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `symbol` | `GraphNode \| None` | The resolved symbol, or `None` when unresolved. |
| `nodes` | `list[GraphNode]` | Ego-graph nodes. |
| `edges` | `list[GraphEdge]` | Ego-graph edges, forward and reverse; includes synthesised `CONTAINS` edges and, when `IMPORTS` is requested, file import edges. |
| `rationale` | `list[dict[str, Any]]` | Rationale comments attached to the symbol. |
| `doc_links` | `list[dict[str, Any]]` | Up to five documentation/config links for chunks in the symbol's file. |
| `outcome` | `str` | `resolved` (default), `ambiguous`, or `not_found`. |
| `candidates` | `list[dict[str, Any]]` | Ranked candidates when the reference was ambiguous. |
| `truncated` | `bool` | Whether a per-node cap trimmed the ego graph: incoming or outgoing edges beyond the 50-edge fanout limit, or a container's declaration list cut short. |
| `stats` | `dict[str, Any]` | Traversal statistics. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return the structured (JSON) explain answer. |
