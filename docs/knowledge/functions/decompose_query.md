---
type: Function
title: "decompose_query"
description: "Tokenize and decompose a full query into its sub-word set."
resource: src/engine/search.py#decompose_query
tags: [search, tokenization, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Tokenizes a full query via [`tokenize`](/functions/tokenize.md) and
decomposes each token into sub-words via
[`identify_subwords`](/functions/identify_subwords.md), producing the
full sub-word set used for FTS5 query construction. Defined in
[`engine.search`](/modules/engine/search.md).

# Signature

`def decompose_query(query: str) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

List of decomposed sub-word tokens.
