---
type: Class
title: "BoostVerdict"
description: "Final bounded boost/no-boost decision produced by the match-boost pass for a single candidate."
resource: src/engine/match_boost.py#BoostVerdict
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Final bounded boost/no-boost decision produced for a single candidate
result by the match-boost pass, derived from
[`MatchEvidence`](/types/MatchEvidence.md). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `boost_factor` | `float` | Multiplicative score adjustment (bounded). |
| `reason` | `str` | Human-readable explanation of the verdict. |
