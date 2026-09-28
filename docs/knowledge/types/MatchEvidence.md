---
type: Class
title: "MatchEvidence"
description: "Per-result name-matching evidence used by the match-boost pass (match_boost.py variant)."
resource: src/engine/match_boost.py#MatchEvidence
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Per-result evidence describing how a candidate's symbol name matched the
query's named tokens (see [`QueryNameContext`](/types/QueryNameContext.md)),
consumed to compute a [`BoostVerdict`](/types/BoostVerdict.md). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

> **Note:** A distinct class also named `MatchEvidence` exists in
> `confidence.py` — see [`ConfidenceMatchEvidence`](/types/ConfidenceMatchEvidence.md).
> The two are unrelated; this concept documents the `match_boost.py` class.

# Schema

| Field | Type | Description |
|---|---|---|
| `tier` | `MatchTier` | Strength of the name match. |
| `matched_token` | `str \| None` | The query token that matched, if any. |
