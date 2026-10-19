---
type: Class
title: "ConfidenceMatchEvidence"
description: "Per-result facts used for confidence computation (confidence.py's MatchEvidence, renamed here to avoid collision)."
resource: code_search/engine/confidence.py#MatchEvidence
tags: [confidence, ranking, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/confidence.py
    id: source-code
---

# Overview

Per-result facts used to compute a confidence score, paired with
[`QueryMatchContext`](QueryMatchContext.md). Defined in
[`engine.confidence`](../modules/engine/confidence.md) as `MatchEvidence`.

> **Naming note:** The source class is named `MatchEvidence`, identical to
> an unrelated class in `match_boost.py` (see
> [`MatchEvidence`](MatchEvidence.md)). This concept file is named
> `ConfidenceMatchEvidence` only to avoid a filename collision in this flat
> `types/` directory; the class itself is still called `MatchEvidence` in
> code.

# Schema

| Field | Type | Description |
|---|---|---|
| `query_subwords` | `list[str]` | The query's decomposed sub-words. |
| `chunk_subwords` | `list[str]` | The candidate chunk's indexed sub-words. |
| `vector_score` | `float` | The raw cosine in `[0, 1]`; `0.0` when the vector arm produced no hit. |
| `fqn` | `str` | The candidate's fully qualified name. |
| `is_definition` | `bool` | Whether the chunk is the symbol's definition site. |
| `content` | `str` | The chunk source. |
| `file_path` | `str` | The containing file path (controller filename fallback). |
| `query_identifier` | `str \| None` | Optional copy of the query's bare identifier. |
| `concept_ratio` | `float` | IDF-weighted fraction of the query's distinctive terms found in the symbol name; `0.0` (default) when the concept-symbol pass did not fire. |
| `endpoint_match` | `bool` | Whether the chunk is an annotated endpoint definition for the query's HTTP verb; default `False`. |
| `config_intent` | `bool` | Whether the query asks for configuration content; default `False`. |
| `content_type` | `str` | The chunk's content axis (`code`, `config`, or `docs`); default `code`. |
