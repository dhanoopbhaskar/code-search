---
type: Function
title: "tokenize"
description: "Tokenization and identifier decomposition of raw text."
resource: code_search/engine/search.py#tokenize
tags: [search, tokenization, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Tokenizes raw text into lowercased alphanumeric-identifier tokens,
splitting on any non-identifier character. Defined in
[`engine.search`](../modules/engine/search.md).

# Signature

`def tokenize(text: str, filter_stopwords: bool = False) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `text` | `str` | The raw text to tokenize. |
| `filter_stopwords` | `bool` | Whether to drop stopwords from the result. |

# Returns

List of word tokens.
