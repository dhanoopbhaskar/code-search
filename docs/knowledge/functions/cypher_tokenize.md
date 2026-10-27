---
type: Function
title: "cypher_tokenize"
description: "Split Cypher query text into tokens for the read-only subset's parser."
resource: code_search/engine/cypher.py#tokenize
tags: [engine, function, cypher]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

The lexer for the read-only Cypher subset: it strips comments and emits
[`Token`](../types/CypherToken.md) records ending with `EOF`. Named
`cypher_tokenize` in this bundle to stay distinct from the search-side
[`tokenize`](tokenize.md) in [`engine.search`](../modules/engine/search.md).
Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Signature

`def tokenize(text: str) -> list[Token]`

# Parameters

| Name | Description |
|---|---|
| `text` | Cypher query text. |

# Returns

Tokens ending with an `EOF` token.

# Raises

- [`CypherError`](../types/CypherError.md): on an unterminated string or
  backtick identifier, or a character that is not part of the supported subset.
