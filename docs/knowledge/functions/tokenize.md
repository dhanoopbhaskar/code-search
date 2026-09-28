---
type: Function
title: "tokenize"
description: "Tokenization and identifier decomposition of raw text."
resource: src/engine/search.py#tokenize
tags: [search, tokenization, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Tokenizes raw text into words, splitting on whitespace and punctuation.
Defined in [`engine.search`](/modules/engine/search.md).

# Signature

`def tokenize(text: str) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `text` | `str` | The raw text to tokenize. |

# Returns

List of word tokens.
