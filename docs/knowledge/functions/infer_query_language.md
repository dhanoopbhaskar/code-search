---
type: Function
title: "infer_query_language"
description: "Infer a query's language."
resource: code_search/engine/language.py#infer_query_language
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/language.py
    id: source-code
---

# Overview

Infers a query's programming language using symbol, then single-language
vocabulary priority (an explicit language argument is handled by the
caller and never overridden here). Defined in
[`engine.language`](../modules/engine/language.md).

# Signature

`def infer_query_language(query: str, symbol_store: Any \| None = None, vocab_by_language: dict[str, set[str]] \| None = None) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw user query. |
| `symbol_store` | `Any \| None` | Optional symbol store used to resolve single-token queries to an exact symbol with a known language. |
| `vocab_by_language` | `dict[str, set[str]] \| None` | Per-language exact sub-word vocabularies, as returned by `language_vocabularies`. |

# Returns

The inferred language name, or `None` when the language is ambiguous or undeterminable.
