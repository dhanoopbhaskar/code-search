---
type: Function
title: "classify_path_match"
description: "Per-signal classifier detecting path-segment match strength."
resource: src/engine/match_boost.py#classify_path_match
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Classifies how strongly a candidate's file path segments match the
query, returning a [`MatchTier`](../types/MatchTier.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def classify_path_match(context: QueryNameContext, file_path: str, *, min_prefix: int = 3, keywords_min: int = 2) -> tuple[MatchTier, float]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context` | `QueryNameContext` | The request-scoped name context. |
| `file_path` | `str` | The candidate chunk's file path. |
| `min_prefix` | `int` | Minimum length for an eligible query term and a matched path term. |
| `keywords_min` | `int` | Minimum eligible query terms required to run the pass. |

# Returns

`(MatchTier.stem | MatchTier.path_term | MatchTier.none, match_ratio)`.
