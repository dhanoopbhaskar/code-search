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
returning a [`MatchTier`](../types/MatchTier.md). Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def classify_symbol_match(context: QueryNameContext, fqn: str, is_definition: bool) -> MatchTier`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context` | `QueryNameContext` | The request-scoped name context. |
| `fqn` | `str` | The candidate chunk's fully qualified name. |
| `is_definition` | `bool` | Whether the chunk is the symbol's definition site. |

# Returns

`exact_fqn`, `exact_symbol`, or `none`.
