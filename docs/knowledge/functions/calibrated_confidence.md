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
[`confidence_score`](/functions/confidence_score.md) with exact-match
evidence boosts (FQN/symbol/controller matches). Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def calibrated_confidence(evidence: ConfidenceMatchEvidence, context: QueryMatchContext) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `evidence` | `ConfidenceMatchEvidence` | Per-result facts. |
| `context` | `QueryMatchContext` | Query-level facts. |

# Returns

Calibrated confidence score in `[0.0, 1.0]`.
