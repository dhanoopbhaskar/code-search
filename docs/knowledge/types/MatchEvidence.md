---
type: Class
title: "MatchEvidence"
description: "Per-result name-matching evidence used by the match-boost pass (match_boost.py variant)."
resource: code_search/engine/match_boost.py#MatchEvidence
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/match_boost.py
    id: source-code
---

# Overview

Per-result evidence describing how a candidate's symbol name matched the
query's named tokens (see [`QueryNameContext`](QueryNameContext.md)),
consumed to compute a [`BoostVerdict`](BoostVerdict.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

> **Note:** A distinct class also named `MatchEvidence` exists in
> `confidence.py` — see [`ConfidenceMatchEvidence`](ConfidenceMatchEvidence.md).
> The two are unrelated; this concept documents the `match_boost.py` class.

# Schema

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `int` | The candidate chunk id. |
| `tier` | `MatchTier` | The strongest applicable match tier. |
| `match_ratio` | `float` | Fraction of significant terms matched for the proportional tiers; `1.0` for the exact tiers and `0.0` for `none`. |
| `is_demoted_role` | `bool` | Whether the chunk is a test/non-canonical/infra/ resource/analysis chunk. |
| `has_independent_evidence` | `bool` | Whether the chunk already carries a non-zero lexical or vector contribution in the fused pool. |
