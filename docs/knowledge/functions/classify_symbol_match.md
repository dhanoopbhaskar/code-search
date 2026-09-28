---
type: Function
title: "classify_symbol_match"
description: "Per-signal classifier detecting symbol-name match strength."
resource: src/engine/match_boost.py#classify_symbol_match
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Classifies how strongly a candidate's symbol name matches the query,
returning a [`MatchTier`](/types/MatchTier.md). Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def classify_symbol_match(symbol_name: str, query_tokens: list[str]) -> MatchTier`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol_name` | `str` | The candidate's short symbol name. |
| `query_tokens` | `list[str]` | Named tokens extracted from the query. |

# Returns

The classified [`MatchTier`](/types/MatchTier.md).
