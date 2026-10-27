---
type: Class
title: "CypherToken"
description: "One lexical token produced by the Cypher lexer: kind, value, and source offset."
resource: code_search/engine/cypher.py#Token
tags: [cypher, lexer, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

Produced by [`tokenize`](../functions/tokenize.md), which strips `//` line
comments and `/* */` block comments before emitting tokens and always terminates
the stream with an `EOF` token. Defined in
[`engine.cypher`](../modules/engine/cypher.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `kind` | `str` | Token category (`EOF`, punctuation, name, number, string, …) |
| `value` | `str` | The token text as written |
| `pos` | `int` | Offset of the token in the query text, used in error messages |

# Lexical Rules

| Rule | Detail |
|---|---|
| Punctuation | `()[]{},.:-|*+/%<>=;$` |
| Multi-character punctuation | `..`, `<=`, `>=`, `<>`, `!=`, `=~` |
| Strings | Single- or double-quoted, read by `_read_string` |
| Identifiers | Bare names, or backtick-quoted via `_read_backtick` |
| Numbers | Integer or decimal, converted by `_number` |
| Whitespace | Space, tab, CR, LF |

An unterminated string or backtick identifier, or any character outside the
subset, raises [`CypherError`](CypherError.md) rather than being skipped.
