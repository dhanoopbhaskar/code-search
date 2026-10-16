---
type: Class
title: "QueryMatchContext"
description: "Query-level name-resolution facts (identifier, qualified name, ambiguity, resolution outcome) computed once per request for confidence scoring."
resource: code_search/engine/confidence.py#QueryMatchContext
tags: [confidence, ranking, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/confidence.py
    id: source-code
---

# Overview

Query-level name-resolution facts computed once per request and reused
per candidate during confidence scoring: the query's bare identifier and
qualified name, whether it is ambiguous, and whether it resolves to an
indexed symbol. Defined in
[`engine.confidence`](../modules/engine/confidence.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `query_identifier` | `str \| None` | The query's bare identifier, or `None`. |
| `qualified_name` | `str \| None` | The query's qualified form (`A.B` / `A::B`), or `None`. |
| `ambiguous` | `bool` | Whether the bare identifier resolves to multiple candidates. |
| `resolved_symbol_name` | `str \| None` | The canonical short name when the query resolves exactly, or `None`. |
| `symbol_resolved` | `bool` | Whether the query is a symbol-shaped reference that resolves to an indexed declaration (outcome `resolved` or `ambiguous`), so the quality gate admits it. |
