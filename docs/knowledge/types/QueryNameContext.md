---
type: Class
title: "QueryNameContext"
description: "Query-level facts about named-symbol tokens extracted from the query, computed once per request."
resource: code_search/engine/match_boost.py#QueryNameContext
tags: [ranking, match-boost, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/match_boost.py
    id: source-code
---

# Overview

Query-level facts about named-symbol tokens extracted from the query
text, computed once per request and reused across all candidate results
during the match-boost pass. Defined in
[`engine.match_boost`](../modules/engine/match_boost.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `raw_query` | `str` | The user query text. |
| `normalized` | `str` | :func:`normalize_name` applied to *raw_query*. |
| `subwords` | `tuple[str, ...]` | The query's decomposed sub-words. |
| `significant_terms` | `tuple[str, ...]` | Sub-words used for proportional path matching (stopwords removed). |
| `query_identifier` | `str \| None` | The query's bare identifier, or `None`. |
| `qualified_name` | `str \| None` | The query's `A.B` / `A::B` form, or `None`. |
| `ambiguous` | `bool` | Whether the bare identifier resolves to multiple candidates. |
| `exact_filename_candidates` | `tuple[int, ...]` | Chunk ids whose file name/stem equals *normalized* within the active content scope. |
