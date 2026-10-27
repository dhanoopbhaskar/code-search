---
type: Class
title: "CachedNeighbor"
description: "Frozen record of one adjacent symbol reached through a stored edge, carrying the edge type and resolution tier."
resource: code_search/engine/graph_cache.py#CachedNeighbor
tags: [graph, cache, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

One hop yielded by [`GraphSnapshot`](GraphSnapshot.md)'s `iter_out`/`iter_in`.
Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `symbol_id` | `int` | The neighbour on the other end of the edge |
| `edge_type` | `str` | Stored edge type (`CALLS`, `USAGE`, `IMPLEMENTS`, …) |
| `resolution_tier` | `str \| None` | How the edge target resolved (`exact`, `conventional`, `same_file`, `range`, `fallback`) |

Only edges with a resolved target appear, so `symbol_id` always names a real
snapshot entry. Consumers turn the tier into a confidence label with
[`resolve_confidence`](../functions/resolve_confidence.md).
