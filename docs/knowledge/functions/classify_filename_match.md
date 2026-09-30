---
type: Function
title: "classify_filename_match"
description: "Per-signal classifier detecting filename-level match strength."
resource: src/engine/match_boost.py#classify_filename_match
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Classifies how strongly a candidate's file name matches the query,
returning a [`MatchTier`](../types/MatchTier.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def classify_filename_match(context: QueryNameContext, file_path: str) -> MatchTier`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context` | `QueryNameContext` | The request-scoped name context. |
| `file_path` | `str` | The candidate chunk's file path. |

# Returns

`exact_filename` or `none`.
