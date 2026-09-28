---
type: Function
title: "subword_overlap"
description: "Compute the fraction of query sub-words present in a candidate's text."
resource: src/engine/confidence.py#subword_overlap
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Computes the fraction of query sub-words present in a candidate's text,
the base lexical overlap signal feeding
[`confidence_score`](/functions/confidence_score.md). Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def subword_overlap(query_subwords: list[str], candidate_text: str) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_subwords` | `list[str]` | Sub-word tokens from the query. |
| `candidate_text` | `str` | The candidate result's text. |

# Returns

Overlap fraction in `[0.0, 1.0]`.
