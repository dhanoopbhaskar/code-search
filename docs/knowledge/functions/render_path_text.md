---
type: Function
title: "render_path_text"
description: "Render a PathAnswer as a hop-by-hop chain."
resource: code_search/engine/graph_query.py#render_path_text
tags: [graph, function, rendering]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Formats a [`PathAnswer`](../types/PathAnswer.md) as a header
(`source -> target`, hop count, directed or undirected) followed by one line
per hop with its relation and confidence label; reverse hops are drawn with
`<--`. Non-`resolved` outcomes render the outcome, explanation, and up to
three candidate FQNs. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def render_path_text(answer: PathAnswer) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `answer` | [`PathAnswer`](../types/PathAnswer.md) | The shortest-path result. |

# Returns

The rendered text.
