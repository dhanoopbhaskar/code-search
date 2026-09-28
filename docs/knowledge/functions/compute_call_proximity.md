---
type: Function
title: "compute_call_proximity"
description: "Inverse call-graph depth between two symbols."
resource: src/engine/semantic_signals.py#compute_call_proximity
tags: [ranking, semantics, graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes the inverse call-graph depth between two symbols via
[`EdgeStore.get_call_graph`](/types/EdgeStore.md), used as a proximity
signal. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def compute_call_proximity(edge_store: EdgeStore, symbol_id_a: int, symbol_id_b: int) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `edge_store` | `EdgeStore` | Graph edge store to traverse. |
| `symbol_id_a` | `int` | First symbol's id. |
| `symbol_id_b` | `int` | Second symbol's id. |

# Returns

Proximity score in `[0.0, 1.0]` (1.0 = directly connected).
