---
type: Function
title: "calibrated_confidence"
description: "Full calibrated confidence for one candidate, combining base score with exact-match evidence boosts."
resource: src/engine/confidence.py#calibrated_confidence
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Computes the full calibrated confidence for one candidate, combining
[`confidence_score`](confidence_score.md) with exact-match
evidence boosts (FQN/symbol/controller matches). Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def calibrated_confidence(evidence: MatchEvidence, context: QueryMatchContext) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `evidence` | `MatchEvidence` | The candidate's per-result match facts. |
| `context` | `QueryMatchContext` | The query-level match context. |

# Returns

The calibrated confidence in `[0.0, 1.0]`.
