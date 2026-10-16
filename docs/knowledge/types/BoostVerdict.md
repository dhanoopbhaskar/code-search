---
type: Class
title: "BoostVerdict"
description: "Final bounded boost/no-boost decision produced by the match-boost pass for a single candidate."
resource: code_search/engine/match_boost.py#BoostVerdict
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/match_boost.py
    id: source-code
---

# Overview

Final bounded boost/no-boost decision produced for a single candidate
result by the match-boost pass, derived from
[`MatchEvidence`](MatchEvidence.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `tier` | `MatchTier` | The tier the boost was applied for (the dampened `stem` tier when a generic-stem `exact_filename` was reduced). |
| `boost` | `float` | The additive amount added to the fused score. |
| `applied` | `bool` | `False` when the tier was withheld (demoted role or a generic stem without independent evidence). |
