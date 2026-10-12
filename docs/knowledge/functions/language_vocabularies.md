---
type: Function
title: "language_vocabularies"
description: "Map each indexed language to its exact sub-word set."
resource: src/engine/language.py#language_vocabularies
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Maps each indexed language to its exact sub-word vocabulary set, built
from the corpus, used for query-language inference. Defined in
[`engine.language`](../modules/engine/language.md).

# Signature

`def language_vocabularies(db: Any) -> dict[str, set[str]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `Any` | A database exposing a `connect()` context manager whose `code_chunks` table has `language` and `subwords` columns. |

# Returns

A mapping of language name to the set of sub-words observed in that language's chunks; empty when the lookup fails or no rows exist.
