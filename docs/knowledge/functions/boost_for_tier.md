---
type: Function
title: "boost_for_tier"
description: "Bounded additive boost for a match tier."
resource: code_search/engine/match_boost.py#boost_for_tier
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/match_boost.py
    id: source-code
---

# Overview

Returns the bounded additive score boost associated with a given
[`MatchTier`](../types/MatchTier.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def boost_for_tier(tier: MatchTier, weight: float, strength: float, pool_max: float, cap: float) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `tier` | `MatchTier` | The match tier the boost applies to. |
| `weight` | `float` | The configured per-tier multiplier. |
| `strength` | `float` | The per-tier strength (`1.0` for exact tiers, the `match_ratio` for proportional tiers). |
| `pool_max` | `float` | The current highest fused score. |
| `cap` | `float` | The maximum per-chunk boost multiplier. |

# Returns

The additive boost, never negative and never above `cap * pool_max`.
