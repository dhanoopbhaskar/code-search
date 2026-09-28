---
type: Class
title: "QueryNameContext"
description: "Query-level facts about named-symbol tokens extracted from the query, computed once per request."
resource: src/engine/match_boost.py#QueryNameContext
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Query-level facts about named-symbol tokens extracted from the query
text, computed once per request and reused across all candidate results
during the match-boost pass. Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `named_tokens` | `list[str]` | Identifier-like tokens extracted from the query. |
| `has_named_tokens` | `bool` | Whether any named tokens were found. |
