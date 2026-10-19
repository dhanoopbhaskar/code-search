---
type: Function
title: "morphological_variants"
description: "Return a word plus conservative English base forms (plural, gerund, past tense)."
resource: code_search/engine/query_terms.py#morphological_variants
tags: [query, function, normalization]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/query_terms.py
    id: source-code
---

# Overview

Bridges natural-language inflection and the indexed identifier vocabulary
(`following` -> `follow`, `favorites` -> `favorite`, `updated` ->
`updat`/`update`). The original word is always first and duplicates are
dropped. Words shorter than four characters, or that are not all-lowercase
alphabetic, are returned unchanged so code identifiers keep their exact
form. Handles `-ies`, `-ing` (including doubled consonants and a restored
trailing `e`), `-ed`, `-es`/`-s`, and `-ly`. Defined in
[`engine.query_terms`](../modules/engine/query_terms.md); called by
[`decompose_query`](decompose_query.md).

# Signature

`def morphological_variants(word: str) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `word` | `str` | A lowercased query sub-word. |

# Returns

The variant list, starting with *word*.
