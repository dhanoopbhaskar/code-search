---
type: Module
title: "engine.query_terms"
description: "Pure, rule-based query normalization: morphological variants and concept-term collapsing."
resource: code_search/engine/query_terms.py
tags: [engine, query, normalization]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/query_terms.py
    id: source-code
---

# Overview

Natural-language queries use inflected forms (`favoriting`, `following`,
`registered`) while indexed code uses the stem (`favorite`, `follow`,
`register`). This module supplies the morphological variants used by the
lexical and confidence layers, plus a concept collapse that stops one word's
variants from diluting the coverage denominator. The rules are conservative:
they touch only all-lowercase words, never identifiers that already
decomposed cleanly, always keep the original word first, and perform no I/O.

# Key Functions

- [`morphological_variants`](../../functions/morphological_variants.md) — a word plus its base forms.
- [`collapse_terms`](../../functions/collapse_terms.md) — one representative per prefix-related group.
- [`concept_terms`](../../functions/concept_terms.md) — collapsed terms filtered by minimum length.

# Internal Helpers

`_restore_e` re-adds a trailing `e` that `-ing`/`-ed` removal dropped
(`favorit` -> `favorite`) when the base ends in `t`, `g`, `c`, `s`, `v`, `z`,
or `k`; `_prefix_related` tests the shared-prefix relation used for grouping.
`_MIN_INFLECTED_LENGTH` (4) is the shortest word that is inflected.

# Consumers

[`engine.search`](search.md) (`decompose_query`, concept-symbol and
endpoint passes) and [`engine.confidence`](confidence.md) (coverage
computation).
