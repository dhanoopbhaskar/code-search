---
type: Class
title: "QueryMatchContext"
description: "Query-level facts computed once per request and reused across all candidate results in confidence scoring."
resource: src/engine/confidence.py#QueryMatchContext
tags: [confidence, ranking, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Query-level facts computed once per request (e.g. token counts, coverage
denominators) and reused across all candidate results during confidence
scoring. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `query_token_count` | `int` | Number of meaningful tokens in the query. |
| `has_definition_intent` | `bool` | Whether the query expresses definition-seeking intent. |
