---
type: Class
title: "QueryAnalysis"
description: "The query-time trust-signal entity produced by analyze_query and consumed by the search/rerank pipeline."
resource: src/engine/language.py#QueryAnalysis
tags: [language, query-analysis, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

The query-time trust-signal entity produced by
[`analyze_query`](/functions/analyze_query.md) and consumed throughout
the search/rerank pipeline. Defined in
[`engine.language`](/modules/engine/language.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `expanded_text` | `str` | Query text after applying [`ExpansionTable`](/types/ExpansionTable.md) expansion. |
| `exact_tokens` | `list[str]` | Exact corpus-vocabulary sub-words matched in the query. |
| `coverage` | `float` | Fraction of expanded tokens matched against corpus vocabulary. |
| `inferred_language` | `str \| None` | Inferred programming language (explicit > symbol > vocab priority). |
| `definition_intent` | `bool` | Whether the query expresses definition-seeking phrasing. |
| `definition_target` | `str \| None` | The resolved symbol target when `definition_intent` is true. |
