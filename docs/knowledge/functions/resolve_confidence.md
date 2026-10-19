---
type: Function
title: "resolve_confidence"
description: "Map a persisted edge resolution tier to an EXTRACTED/INFERRED/AMBIGUOUS/UNRESOLVED label."
resource: code_search/engine/graph_query.py#resolve_confidence
tags: [graph, function, confidence]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Translates the `resolution_tier` stored on a graph edge into the confidence
label shown on every rendered edge. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def resolve_confidence(resolution_tier: str | None, resolved: bool = True) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `resolution_tier` | `str \| None` | Persisted tier: `exact`, `conventional`, `same_file`, `range`, `fallback`, or `None`. |
| `resolved` | `bool` | Whether the edge target resolved to a symbol. |

# Returns

`UNRESOLVED` when *resolved* is false; otherwise `EXTRACTED` for
`exact`/`conventional`, `INFERRED` for `same_file`/`range`, `AMBIGUOUS` for
`fallback`, and `INFERRED` for an unknown or missing tier.
