---
type: Function
title: "confidence_score"
description: "Base lexical/vector blend confidence score for one candidate."
resource: code_search/engine/confidence.py#confidence_score
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/confidence.py
    id: source-code
---

# Overview

Computes the base confidence score for one candidate by blending lexical
overlap and vector similarity, prior to calibration. Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def confidence_score(query_subwords: list[str], chunk_subwords: list[str], vector_score: float = 0.0) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_subwords` | `list[str]` | The query's decomposed sub-words. |
| `chunk_subwords` | `list[str]` | The chunk's indexed sub-words. |
| `vector_score` | `float` | The chunk's raw (pre-normalization) vector cosine in `[0.0, 1.0]`; `0` when the vector arm produced no hit. |

# Returns

The blended confidence in `[0.0, 1.0]`.
