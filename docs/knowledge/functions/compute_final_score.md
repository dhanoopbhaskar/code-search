---
type: Function
title: "compute_final_score"
description: "Fuse semantic signals with vector similarity."
resource: src/engine/semantic_signals.py#compute_final_score
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Fuses [`SemanticSignals`](../types/SemanticSignals.md) with the candidate's
vector similarity score to produce the final
[`RelevanceScore`](../types/RelevanceScore.md). Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Signature

`def compute_final_score(semantic_signals: SemanticSignals, vector_similarity: float, weights: dict[str, float], semantic_blend: float) -> RelevanceScore`

# Parameters

| Name | Type | Description |
|---|---|---|
| `semantic_signals` | `SemanticSignals` | Computed semantic signals |
| `vector_similarity` | `float` | Cosine similarity from vector search [0.0, 1.0] |
| `weights` | `dict[str, float]` | Dict with keys 'package', 'type', 'call_graph' |
| `semantic_blend` | `float` | Alpha parameter in [0.0, 1.0] |

# Returns

RelevanceScore with semantic, vector, and final scores
