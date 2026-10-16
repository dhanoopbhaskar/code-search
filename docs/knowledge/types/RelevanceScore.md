---
type: Class
title: "RelevanceScore"
description: "Final combined relevance score from structural semantic signals and vector similarity."
resource: code_search/engine/semantic_signals.py#RelevanceScore
tags: [ranking, semantics, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/semantic_signals.py
    id: source-code
---

# Overview

Final combined relevance score for a `find_related` candidate, blending
the structural [`SemanticSignals`](SemanticSignals.md) score with the
candidate's vector similarity. Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `semantic_score` | `float` | Weighted combination of the three structural signals. |
| `vector_score` | `float` | Raw cosine similarity from the vector-search arm. |
| `final_score` | `float` | Blend of `semantic_score` and `vector_score`. |
