---
type: Function
title: "compute_verdict"
description: "Bounded boost verdict for one candidate."
resource: src/engine/match_boost.py#compute_verdict
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Computes the bounded [`BoostVerdict`](/types/BoostVerdict.md) for one
candidate result, combining its [`MatchEvidence`](/types/MatchEvidence.md)
with the query's [`QueryNameContext`](/types/QueryNameContext.md).
Defined in [`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def compute_verdict(evidence: MatchEvidence, context: QueryNameContext) -> BoostVerdict`

# Parameters

| Name | Type | Description |
|---|---|---|
| `evidence` | `MatchEvidence` | Per-result name-matching evidence. |
| `context` | `QueryNameContext` | Query-level named-token context. |

# Returns

The computed [`BoostVerdict`](/types/BoostVerdict.md).
