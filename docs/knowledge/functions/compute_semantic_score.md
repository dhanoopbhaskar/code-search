---
type: Function
title: "compute_semantic_score"
description: "Compute all three semantic signals for a candidate."
resource: code_search/engine/semantic_signals.py#compute_semantic_score
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes all three semantic signals — package overlap, type sharing, call
proximity — for a candidate, bundling them into a
[`SemanticSignals`](../types/SemanticSignals.md) instance. Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Signature

`def compute_semantic_score(anchor: dict[str, Any], candidate: dict[str, Any], db: GraphDatabase, max_call_depth: int = 3, call_depths: dict[int, int] \| None = None) -> SemanticSignals`

# Parameters

| Name | Type | Description |
|---|---|---|
| `anchor` | `dict[str, Any]` | Anchor symbol dict with fqn, file_path, symbol_id |
| `candidate` | `dict[str, Any]` | Candidate symbol dict with fqn, file_path, symbol_id |
| `db` | `GraphDatabase` | Graph database |
| `max_call_depth` | `int` | Maximum call graph traversal depth |
| `call_depths` | `dict[int, int] \| None` | Optional precomputed {symbol_id: depth} map for the anchor (avoids one CTE pair per candidate during reranking) |

# Returns

SemanticSignals with all three scores
