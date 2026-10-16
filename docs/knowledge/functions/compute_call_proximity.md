---
type: Function
title: "compute_call_proximity"
description: "Inverse call-graph depth between two symbols."
resource: code_search/engine/semantic_signals.py#compute_call_proximity
tags: [ranking, semantics, graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes the inverse call-graph depth between two symbols by running a
recursive `CALLS`-edge traversal (in both caller and callee directions) over
the [`GraphDatabase`](../types/GraphDatabase.md) connection, used as a
proximity signal. Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Signature

`def compute_call_proximity(db: GraphDatabase, anchor_symbol_id: int, candidate_symbol_id: int, max_depth: int = 3) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `GraphDatabase` | Graph database connection |
| `anchor_symbol_id` | `int` | Anchor symbol ID |
| `candidate_symbol_id` | `int` | Candidate symbol ID |
| `max_depth` | `int` | Maximum traversal depth (default 3) |

# Returns

Call proximity score in [0.0, 1.0]
