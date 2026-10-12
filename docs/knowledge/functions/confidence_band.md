---
type: Function
title: "confidence_band"
description: "Map a calibrated confidence score to a discrete band label (high/medium/low)."
resource: src/engine/confidence.py#confidence_band
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Maps a calibrated confidence score to a discrete band label
(`"high"`/`"medium"`/`"low"`) for response envelope display. Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def confidence_band(score: float, high_floor: float, medium_floor: float) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `score` | `float` | The blended confidence score. |
| `high_floor` | `float` | The score at which a result becomes `high`. |
| `medium_floor` | `float` | The score below which a result is `low`. |

# Returns

One of `"high"`, `"medium"`, or `"low"`.
