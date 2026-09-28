---
type: Function
title: "boost_for_tier"
description: "Bounded additive boost for a match tier."
resource: src/engine/match_boost.py#boost_for_tier
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Returns the bounded additive score boost associated with a given
[`MatchTier`](/types/MatchTier.md). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def boost_for_tier(tier: MatchTier) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `tier` | `MatchTier` | The match strength tier. |

# Returns

The bounded boost value for that tier.
