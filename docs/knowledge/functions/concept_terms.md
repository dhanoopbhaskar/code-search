---
type: Function
title: "concept_terms"
description: "Return collapsed concept terms of at least a minimum length."
resource: code_search/engine/query_terms.py#concept_terms
tags: [query, function, normalization]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/query_terms.py
    id: source-code
---

# Overview

[`collapse_terms`](collapse_terms.md) followed by a length filter. Defined in
[`engine.query_terms`](../modules/engine/query_terms.md).

# Signature

`def concept_terms(terms: Iterable[str], min_length: int = 3) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `terms` | `Iterable[str]` | Query sub-words. |
| `min_length` | `int` | Minimum representative length to keep. |

# Returns

The collapsed terms that are at least *min_length* characters long.
