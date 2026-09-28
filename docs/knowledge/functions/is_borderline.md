---
type: Function
title: "is_borderline"
description: "Whether a confidence score falls in the borderline zone between bands."
resource: src/engine/confidence.py#is_borderline
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Returns whether a confidence score falls in the borderline zone between
two bands, used to decide whether to widen the rescue tier. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def is_borderline(score: float) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `score` | `float` | A calibrated confidence score. |

# Returns

`True` if the score is near a band boundary.
