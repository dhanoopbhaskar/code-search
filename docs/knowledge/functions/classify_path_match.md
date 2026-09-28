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
query, returning a [`MatchTier`](/types/MatchTier.md). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def classify_path_match(file_path: str, query_tokens: list[str]) -> MatchTier`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | The candidate's file path. |
| `query_tokens` | `list[str]` | Named tokens extracted from the query. |

# Returns

The classified [`MatchTier`](/types/MatchTier.md).
