---
type: Function
title: "strongest_tier"
description: "Highest-priority tier in an iterable."
resource: src/engine/match_boost.py#strongest_tier
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Returns the highest-priority [`MatchTier`](/types/MatchTier.md) from an
iterable of tiers (EXACT > PREFIX > FUZZY > NONE). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def strongest_tier(tiers: Iterable[MatchTier]) -> MatchTier`

# Parameters

| Name | Type | Description |
|---|---|---|
| `tiers` | `Iterable[MatchTier]` | Candidate tiers to compare. |

# Returns

The strongest tier present.
