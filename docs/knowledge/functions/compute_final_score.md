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

Fuses [`SemanticSignals`](/types/SemanticSignals.md) with the candidate's
vector similarity score to produce the final
[`RelevanceScore`](/types/RelevanceScore.md). Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def compute_final_score(signals: SemanticSignals, cosine_similarity: float) -> RelevanceScore`

# Parameters

| Name | Type | Description |
|---|---|---|
| `signals` | `SemanticSignals` | The computed semantic signal bundle. |
| `cosine_similarity` | `float` | The candidate's vector-search cosine similarity. |

# Returns

The final [`RelevanceScore`](/types/RelevanceScore.md).
