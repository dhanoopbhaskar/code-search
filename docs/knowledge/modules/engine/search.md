---
type: Module
title: "engine.search"
description: "Hybrid BM25 + vector search engine with RRF fusion, quality gates, rescue tiers, and match-boost reranking."
resource: src/engine/search.py
tags: [engine, search, ranking, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Implements hybrid search combining BM25 keyword retrieval (sparse,
lexical) and vector semantic search (dense) using Reciprocal Rank Fusion
(RRF). This is the core search engine layer of code-search, providing
ranked, exhaustive (line-wise), and enumerate (symbol-list) modes. Three
layers separate concerns: [`BM25Search`](/types/BM25Search.md) (FTS5
keyword retrieval), [`VectorSearch`](/types/VectorSearch.md) (semantic
embedding lookups), and [`HybridSearch`](/types/HybridSearch.md)
(orchestrates the full pipeline with quality gates, rescue tiers,
match-boost overlays, and reranking signals such as symbol resolution,
file-stem rescue, authorization intent, and config scent).

# Key Constants

| Constant | Purpose |
|---|---|
| `DEFAULT_CONTENT_SCOPE` | Default content axis, `"code_focused"` |
| `VALID_CONTENT_SCOPES` | `("code", "config", "docs", "all", "code_focused")` |
| `VALID_MATCHING_SEMANTICS` | `("literal", "all_tokens", "any_token")` for exhaustive mode |
| `STOPWORDS` | ~110 English stopwords removed by optional filter |
| `NON_INFORMATIVE_CODE_TERMS` | ~160 language keywords excluded from informative-token coverage |

# Key Classes

- [`BM25Search`](/types/BM25Search.md) — FTS5-based BM25 keyword search over the indexed corpus.
- [`VectorSearch`](/types/VectorSearch.md) — semantic search using the vector index.
- [`HybridSearch`](/types/HybridSearch.md) — combines both via RRF fusion, with quality gates, rescue ladder, and match-boost.

# Key Functions

- [`tokenize`](/functions/tokenize.md), [`identify_subwords`](/functions/identify_subwords.md), [`decompose_query`](/functions/decompose_query.md) — tokenization and identifier decomposition.
- [`build_fts_query`](/functions/build_fts_query.md) — build an FTS5 MATCH expression from decomposed sub-words.
- [`query_symbol_identifier`](/functions/query_symbol_identifier.md), [`classify_query`](/functions/classify_query.md) — classify a query as symbol-like or natural-language.
- [`exact_precheck`](/functions/exact_precheck.md) — detect concrete literal/annotation/identifier patterns in a query.
- [`chunk_rank_class`](/functions/chunk_rank_class.md) — classify a chunk as code/boilerplate/resource.
- [`rrf_fusion`](/functions/rrf_fusion.md) — Reciprocal Rank Fusion of BM25 and vector result lists.

# Internal Helpers

`HybridSearch` carries dozens of private methods implementing the ranking
pipeline stages: query-quality gating (`_query_quality_gate`), stem rescue
(`_stem_rescue`), embedded-symbol pass (`_embedded_symbol_pass`),
match-boost (`_match_boost_pass`), authorization/config/DDL/migration
scent detection, the rescue ladder (`_rescue_envelope`, `_rescue_t1`,
`_rescue_t2`), exhaustive/enumerate mode implementations
(`_search_exhaustive`, `_search_enumerate`), and file coherence
(`_apply_file_coherence`).
