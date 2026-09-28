---
type: Function
title: "identify_subwords"
description: "Split identifier-style tokens into their constituent sub-words (camelCase/snake_case decomposition)."
resource: src/engine/search.py#identify_subwords
tags: [search, tokenization, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Splits identifier-style tokens (camelCase, snake_case, PascalCase) into
their constituent sub-words. Defined in
[`engine.search`](/modules/engine/search.md).

# Signature

`def identify_subwords(token: str) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `token` | `str` | A single identifier-like token. |

# Returns

List of decomposed sub-word strings.
