---
type: Function
title: "language_vocabularies_for_tokens"
description: "Map languages to the queried tokens they contain, reading only the requested stats rows."
resource: code_search/engine/language.py#language_vocabularies_for_tokens
tags: [language, function, query-analysis]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/language.py
    id: source-code
---

# Overview

Reads only the requested rows from the persisted `subword_stats` table so
query-time language inference never loads every chunk's vocabulary. Falls
back to the full legacy scan ([`language_vocabularies`](language_vocabularies.md))
only when the statistics table is unavailable. Defined in
[`engine.language`](../modules/engine/language.md).

# Signature

`def language_vocabularies_for_tokens(db: Any, tokens: set[str]) -> dict[str, set[str]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `Any` | A database exposing `connect()`. |
| `tokens` | `set[str]` | The query's candidate sub-words. |

# Returns

A mapping of language name to the subset of `tokens` observed in that
language. Empty when no token is present or the lookup fails.
