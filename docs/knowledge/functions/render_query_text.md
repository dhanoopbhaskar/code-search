---
type: Function
title: "render_query_text"
description: "Render a GraphAnswer as compact, agent-friendly text."
resource: code_search/engine/graph_query.py#render_query_text
tags: [graph, function, rendering]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Formats a [`GraphAnswer`](../types/GraphAnswer.md): a header with seeds and
node/edge counts (flagged `truncated` when trimmed), nodes grouped by file
with seeds marked `*`, then the relations rendered by
[`GraphEdge.render`](../types/GraphEdge.md). A `no_seed` outcome yields a
single retry hint. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def render_query_text(answer: GraphAnswer) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `answer` | [`GraphAnswer`](../types/GraphAnswer.md) | The graph query result. |

# Returns

The rendered text.
