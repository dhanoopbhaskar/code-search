---
type: Class
title: "MatchTier"
description: "IntEnum ranking the strongest filename/symbol evidence connecting a query to a chunk."
resource: src/engine/match_boost.py#MatchTier
tags: [ranking, match-boost, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

`IntEnum` ranking the strongest filename or symbol evidence connecting a query to a chunk. Integer values encode priority so the strongest applicable tier wins. Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Values

| Value | Description |
|---|---|
| `none` | No name-based match. |
| `path_term` | A query term matches a path segment. |
| `stem` | The filename stem matches a query term. |
| `exact_filename` | The filename exactly matches the query terms. |
| `exact_symbol` | The symbol name exactly matches the query. |
| `exact_fqn` | The fully qualified name exactly matches the query. |
