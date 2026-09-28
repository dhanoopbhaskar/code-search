---
type: Function
title: "envelope_band"
description: "Aggregate confidence band for the overall response envelope from a list of per-result bands."
resource: src/engine/confidence.py#envelope_band
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Aggregates per-result confidence bands into a single overall band for the
response envelope. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def envelope_band(result_bands: list[str]) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `result_bands` | `list[str]` | Confidence band labels for each result in the response. |

# Returns

The overall envelope band label.
