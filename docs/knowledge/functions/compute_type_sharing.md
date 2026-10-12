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
parameter types between two symbols, with a capped +0.2 bonus when both
symbols' return types match. Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Signature

`def compute_type_sharing(anchor_fqn: str, candidate_fqn: str) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `anchor_fqn` | `str` | Anchor symbol's fully qualified name |
| `candidate_fqn` | `str` | Candidate symbol's fully qualified name |

# Returns

Type sharing score in [0.0, 1.0]
