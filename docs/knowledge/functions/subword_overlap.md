---
type: Function
title: "subword_overlap"
description: "Compute the fraction of query sub-words present in a candidate's text."
resource: code_search/engine/confidence.py#subword_overlap
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/confidence.py
    id: source-code
---

# Overview

Computes the fraction of distinct query concepts present in a candidate's
text, the base lexical overlap signal feeding
[`confidence_score`](confidence_score.md). Query sub-words are first
collapsed with [`collapse_terms`](collapse_terms.md), so a word and its
morphological variants count once. A concept is present when it equals a
chunk sub-word or shares a prefix of at least four characters with one whose
length differs by at most three (`favorit`/`favorite`). Returns `0.0` for an
empty query. Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def subword_overlap(query_subwords: list[str], chunk_subwords: list[str]) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_subwords` | `list[str]` | The query's decomposed sub-words. |
| `chunk_subwords` | `list[str]` | The chunk's indexed sub-words. |

# Returns

The overlap fraction in `[0.0, 1.0]`.
