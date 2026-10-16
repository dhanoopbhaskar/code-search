---
type: Function
title: "demote_test_file_candidates"
description: "Demote test-file chunks inside the candidate pool before fusion."
resource: code_search/engine/reranking.py#demote_test_file_candidates
tags: [ranking, reranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/reranking.py
    id: source-code
---

# Overview

Demotes test-file chunks inside the candidate pool before RRF fusion.
Defined in [`engine.reranking`](../modules/engine/reranking.md); applied
by [`HybridSearch`](../types/HybridSearch.md)'s internal pipeline for
natural-language queries.

# Signature

`def demote_test_file_candidates(bm25_results: list[tuple[int, float]], vector_results: list[tuple[int, float]], test_chunk_ids: set[int], penalty: float) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `bm25_results` | `list[tuple[int, float]]` | `(chunk_rowid, score)` pairs from the lexical arm. |
| `vector_results` | `list[tuple[int, float]]` | `(chunk_rowid, score)` pairs from the dense arm. |
| `test_chunk_ids` | `set[int]` | Row ids of chunks living in test/spec files. |
| `penalty` | `float` | Multiplicative demotion (`noise_penalty`). |

# Returns

The two ranked lists with test-file scores scaled by *penalty*.
