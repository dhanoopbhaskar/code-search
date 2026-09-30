---
type: Function
title: "evaluate_rescue_floor"
description: "Evaluate whether the rescue tier should return results."
resource: src/engine/rescue_floor.py#evaluate_rescue_floor
tags: [ranking, rescue, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/rescue_floor.py
    id: source-code
---

# Overview

Evaluates whether the rescue tier should return results by checking
meaningful lexical token overlap against the `DEFAULT_LEXICAL_THRESHOLD`,
distinguishing gibberish queries from borderline-real ones. Defined in
[`engine.rescue_floor`](../modules/engine/rescue_floor.md).

# Signature

`def evaluate_rescue_floor(query_tokens: list[str], indexed_content_tokens: set[str], lexical_score: float) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_tokens` | `list[str]` | Individual tokens from the user query. |
| `indexed_content_tokens` | `set[str]` | Tokens from the indexed content. |
| `lexical_score` | `float` | Computed lexical relevance score. |

# Returns

dict with keys: - `return_rescue` (bool): Whether to return rescue tier results - `pure_gibberish` (bool): Whether query is pure-gibberish - `borderline_real` (bool): Whether query has one meaningful token - `envelope` (str | None): Envelope text if rescue is gated, None otherwise
