---
type: Function
title: "analyze_query"
description: "Build the QueryAnalysis entity for a query (the one shared rule)."
resource: src/engine/language.py#analyze_query
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Builds the [`QueryAnalysis`](/types/QueryAnalysis.md) entity for a query
— expansion, exact tokens, coverage, inferred language, and definition
intent — as the single shared rule consumed by the search/rerank
pipeline. Defined in [`engine.language`](/modules/engine/language.md).

# Signature

`def analyze_query(query: str, db: GraphDatabase, symbol_store: SymbolStore, explicit_language: str \| None = None) -> QueryAnalysis`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |
| `db` | `GraphDatabase` | Graph database for vocabulary lookups. |
| `symbol_store` | `SymbolStore` | Symbol store for definition-intent resolution. |
| `explicit_language` | `str \| None` | Caller-supplied language filter. |

# Returns

The populated [`QueryAnalysis`](/types/QueryAnalysis.md) entity.
