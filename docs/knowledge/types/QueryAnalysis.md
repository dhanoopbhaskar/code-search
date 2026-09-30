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
[`analyze_query`](../functions/analyze_query.md) — expanded text,
exact-vocabulary tokens, coverage, inferred language, and definition
intent — consumed throughout the search/rerank pipeline. Defined in
[`engine.language`](../modules/engine/language.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `query` | `str` | The raw query as received. |
| `expanded_text` | `str` | The query after synonym/expansion resolution. |
| `exact_tokens` | `list[str]` | Corpus-vocabulary sub-words present in the expanded text (exact matches only, never prefix). |
| `coverage` | `float` | The fraction of concept sub-words that appear exactly in the vocabulary — computed after expansion and gating ordering. |
| `inferred_language` | `str \| None` | The language inferred for the query, or `None` to keep search unscoped. |
| `definition_intent` | `bool` | Whether the query asks for a definition. |
| `definition_target` | `str \| None` | The resolved symbol FQN when definition intent is detected and the target resolves, else `None`. |
