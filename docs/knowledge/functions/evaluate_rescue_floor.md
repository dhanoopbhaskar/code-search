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
[`engine.rescue_floor`](/modules/engine/rescue_floor.md).

# Signature

`def evaluate_rescue_floor(query: str, lexical_coverage: float) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |
| `lexical_coverage` | `float` | Fraction of query tokens present in the corpus vocabulary. |

# Returns

`True` if the rescue tier is allowed to return results.
