---
type: Function
title: "rerank_with_semantic"
description: "Rerank vector results using semantic signals."
resource: src/engine/semantic_signals.py#rerank_with_semantic
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Reranks a list of vector-search results using
[`compute_semantic_score`](/functions/compute_semantic_score.md) and
[`compute_final_score`](/functions/compute_final_score.md) for each
candidate. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def rerank_with_semantic(edge_store: EdgeStore, source: dict[str, Any], results: list[tuple[int, float]]) -> list[RelevanceScore]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `edge_store` | `EdgeStore` | Graph edge store for call-proximity lookups. |
| `source` | `dict[str, Any]` | The source/reference symbol. |
| `results` | `list[tuple[int, float]]` | `(chunk_id, cosine_score)` pairs from vector search. |

# Returns

List of [`RelevanceScore`](/types/RelevanceScore.md) entries, reranked.
