---
type: Function
title: "is_borderline"
description: "Whether a confidence band is borderline (low)."
resource: src/engine/confidence.py#is_borderline
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Returns whether a confidence band is borderline — i.e. `"low"` — so
consumers can flag such results for verification. Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def is_borderline(band: str) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `band` | `str` | One of `"high"`, `"medium"`, or `"low"`. |

# Returns

`True` when *band* is `"low"`.
