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

Builds the [`QueryAnalysis`](../types/QueryAnalysis.md) entity for a query
— expansion, exact tokens, coverage, inferred language, and definition
intent — as the single shared rule consumed by the search/rerank
pipeline. Defined in [`engine.language`](../modules/engine/language.md).

# Signature

`def analyze_query(query: str, settings: Settings, vocabulary: set[str] \| None = None, expansion_table: Any \| None = None, symbol_store: Any \| None = None, vocab_by_language: dict[str, set[str]] \| None = None, explicit_language: str \| None = None) -> QueryAnalysis`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw user query. |
| `settings` | `Settings` | Runtime settings, used to locate the expansion table when none is supplied. |
| `vocabulary` | `set[str] \| None` | The exact corpus vocabulary (all sub-words in the index); when `None`, coverage and exact tokens resolve to zero/empty. |
| `expansion_table` | `Any \| None` | An `ExpansionTable`; built from `expansion_file` when `None`. |
| `symbol_store` | `Any \| None` | Optional symbol store for definition-target resolution and language inference. |
| `vocab_by_language` | `dict[str, set[str]] \| None` | Per-language vocabularies for language inference. |
| `explicit_language` | `str \| None` | Language supplied by the caller; always takes precedence over inferred language. |

# Returns

A `QueryAnalysis` carrying the expanded text, exact tokens, coverage, inferred language, and definition intent.
