---
type: Module
title: "engine.language"
description: "Query-time language inference and definition-intent detection."
resource: src/engine/language.py
tags: [engine, query-analysis, language]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Performs query-time language inference and definition-intent detection.
Produces `expanded_text` (via `ExpansionTable`), `exact_tokens` (exact
corpus-vocabulary sub-words only), `coverage` computed after expansion,
`inferred_language` (explicit > symbol > vocab), and
`definition_intent`/`definition_target` resolved via
[`SymbolStore`](/types/SymbolStore.md).

# Key Classes

- [`QueryAnalysis`](/types/QueryAnalysis.md) — the query-time trust-signal entity produced by `analyze_query` and consumed by the search/rerank pipeline.

# Key Functions

- [`language_vocabularies`](/functions/language_vocabularies.md) — map each indexed language to its exact sub-word set.
- [`infer_query_language`](/functions/infer_query_language.md) — infer a query's language.
- [`detect_definition_intent`](/functions/detect_definition_intent.md) — detect definition phrasing and resolve its target.
- [`embedded_symbols`](/functions/embedded_symbols.md) — resolved symbol short names embedded in a natural-language query.
- [`analyze_query`](/functions/analyze_query.md) — build the `QueryAnalysis` entity for a query (the one shared rule).

# Internal Helpers

`_concept_subwords` and `_clean_symbol_target` are private text-shaping
helpers used by `analyze_query` and `detect_definition_intent`.
