---
type: Function
title: "compute_type_sharing"
description: "Normalized signature comparison score."
resource: src/engine/semantic_signals.py#compute_type_sharing
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes a normalized signature comparison score measuring shared
parameter/return types between two symbols. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def compute_type_sharing(signature_a: str, signature_b: str) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `signature_a` | `str` | First symbol's signature string. |
| `signature_b` | `str` | Second symbol's signature string. |

# Returns

Type-sharing score in `[0.0, 1.0]`.
