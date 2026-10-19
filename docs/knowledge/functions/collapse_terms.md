---
type: Function
title: "collapse_terms"
description: "Collapse prefix-related query terms into one representative per concept."
resource: code_search/engine/query_terms.py#collapse_terms
tags: [query, function, normalization]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/query_terms.py
    id: source-code
---

# Overview

Groups terms that share a prefix of at least `min_prefix` characters (so a
word and its morphological variants count once) and keeps one representative
per group, in first-occurrence order. The shortest member is chosen unless
*preferred* (typically the corpus vocabulary) contains a member, in which
case the shortest preferred member wins; this avoids picking `favorit` when
the corpus spells the word `favorite`. Defined in
[`engine.query_terms`](../modules/engine/query_terms.md); used by
[`engine.confidence`](../modules/engine/confidence.md) so variants do not
dilute the coverage denominator, and by the concept and endpoint ranking
passes in [`engine.search`](../modules/engine/search.md).

# Signature

`def collapse_terms(terms: Iterable[str], min_prefix: int = 4, preferred: set[str] | None = None) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `terms` | `Iterable[str]` | Query sub-words, possibly containing morphological variants. |
| `min_prefix` | `int` | Minimum shared prefix length for two terms to be one concept. |
| `preferred` | `set[str] \| None` | Optional vocabulary of exact forms to prefer. |

# Returns

One representative per concept; empty terms are skipped.
