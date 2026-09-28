---
type: Class
title: "MatchTier"
description: "StrEnum classifying how strongly a result's name matches the query (exact, prefix, fuzzy, none)."
resource: src/engine/match_boost.py#MatchTier
tags: [ranking, match-boost, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

`StrEnum` classifying how strongly a result's symbol name matches the
query's named tokens. Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Schema

| Value | Description |
|---|---|
| `EXACT` | The symbol name exactly matches a query token. |
| `PREFIX` | The symbol name starts with a query token. |
| `FUZZY` | The symbol name is a close (edit-distance) match. |
| `NONE` | No name-based match. |
