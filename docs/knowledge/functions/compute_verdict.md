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

Computes the bounded [`BoostVerdict`](../types/BoostVerdict.md) for one
candidate result from its [`MatchEvidence`](../types/MatchEvidence.md),
per-tier weights, and the pool/query normalization inputs. Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def compute_verdict(evidence: MatchEvidence, weights: Mapping[MatchTier, float], *, pool_max: float, cap: float, generic_stems: frozenset[str], normalized_query: str) -> BoostVerdict`

# Parameters

| Name | Type | Description |
|---|---|---|
| `evidence` | `MatchEvidence` | The candidate's match evidence. |
| `weights` | `Mapping[MatchTier, float]` | Per-tier weight multipliers. |
| `pool_max` | `float` | The current highest fused score. |
| `cap` | `float` | The maximum per-chunk boost multiplier. |
| `generic_stems` | `frozenset[str]` | The ubiquitous file-stem vocabulary. |
| `normalized_query` | `str` | `normalize_name` applied to the query. |

# Returns

The `BoostVerdict` to apply (`applied=False` when withheld).
