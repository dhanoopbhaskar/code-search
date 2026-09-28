---
type: Function
title: "rrf_fusion"
description: "Reciprocal Rank Fusion of BM25 and vector result lists."
resource: src/engine/search.py#rrf_fusion
tags: [search, ranking, fusion, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Combines BM25 and vector search result lists using Reciprocal Rank
Fusion (RRF), producing a single fused ranking. Defined in
[`engine.search`](/modules/engine/search.md); the core fusion step inside
[`HybridSearch.search`](/types/HybridSearch.md).

# Signature

`def rrf_fusion(bm25_results: list[tuple[int, float]], vector_results: list[tuple[int, float]], k: int = 60) -> list[tuple[int, float]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `bm25_results` | `list[tuple[int, float]]` | `(chunk_id, score)` pairs from [`BM25Search`](/types/BM25Search.md). |
| `vector_results` | `list[tuple[int, float]]` | `(chunk_id, score)` pairs from [`VectorSearch`](/types/VectorSearch.md). |
| `k` | `int` | RRF smoothing constant. |

# Returns

Fused `(chunk_id, rrf_score)` pairs, sorted by fused score descending.
