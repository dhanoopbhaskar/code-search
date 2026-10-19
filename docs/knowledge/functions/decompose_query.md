---
type: Function
title: "decompose_query"
description: "Tokenize and decompose a full query into its sub-word set."
resource: code_search/engine/search.py#decompose_query
tags: [search, tokenization, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Extracts identifier-like tokens from the query with an inline pattern
(`[a-zA-Z_][a-zA-Z0-9_]*`) and decomposes each token into sub-words via
[`identify_subwords`](identify_subwords.md), producing the
deduplicated, order-preserving sub-word set used for FTS5 query
construction. With `expand_variants` (default), each sub-word is followed by
its [`morphological_variants`](morphological_variants.md) so inflected
query words (`following`) can match indexed stems (`follow`); callers that
count terms rather than match them pass `expand_variants=False`. Defined in
[`engine.search`](../modules/engine/search.md).

# Signature

`def decompose_query(query: str, filter_stopwords: bool = False, *, expand_variants: bool = True) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |
| `filter_stopwords` | `bool` | Whether to drop stopwords from the result. |
| `expand_variants` | `bool` | Keyword-only; whether to follow each sub-word with its morphological base forms. |

# Returns

List of decomposed sub-word tokens.
