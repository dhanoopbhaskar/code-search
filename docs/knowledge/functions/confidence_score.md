---
type: Function
title: "confidence_score"
description: "Base lexical/vector blend confidence score for one candidate."
resource: src/engine/confidence.py#confidence_score
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Computes the base confidence score for one candidate by blending lexical
overlap and vector similarity, prior to calibration. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def confidence_score(evidence: ConfidenceMatchEvidence, context: QueryMatchContext) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `evidence` | `ConfidenceMatchEvidence` | Per-result facts (see [`ConfidenceMatchEvidence`](/types/ConfidenceMatchEvidence.md)). |
| `context` | `QueryMatchContext` | Query-level facts (see [`QueryMatchContext`](/types/QueryMatchContext.md)). |

# Returns

Base confidence score in `[0.0, 1.0]`.
