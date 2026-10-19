---
type: Function
title: "render_explain_text"
description: "Render an ExplainAnswer with metadata, relations, rationale, and linked docs."
resource: code_search/engine/graph_query.py#render_explain_text
tags: [graph, function, rendering]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Formats an [`ExplainAnswer`](../types/ExplainAnswer.md): the symbol's kind,
location, signature, and the first 200 characters of its docstring; outgoing
and incoming relations; rationale comments (text clipped to 160 characters);
and linked documentation. Unresolved or ambiguous outcomes render the outcome
plus up to five candidate FQNs. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def render_explain_text(answer: ExplainAnswer) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `answer` | [`ExplainAnswer`](../types/ExplainAnswer.md) | The explain result. |

# Returns

The rendered text.
