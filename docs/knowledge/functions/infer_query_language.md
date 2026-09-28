---
type: Function
title: "infer_query_language"
description: "Infer a query's language."
resource: src/engine/language.py#infer_query_language
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Infers a query's programming language using explicit-flag, symbol, then
vocabulary priority. Defined in
[`engine.language`](/modules/engine/language.md).

# Signature

`def infer_query_language(query: str, vocabularies: dict[str, set[str]], explicit_language: str \| None = None) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |
| `vocabularies` | `dict[str, set[str]]` | Per-language vocabulary sets from [`language_vocabularies`](/functions/language_vocabularies.md). |
| `explicit_language` | `str \| None` | A caller-supplied language filter, given highest priority. |

# Returns

The inferred language name, or `None` if undetermined.
