---
type: Module
title: "engine.search"
description: "Hybrid BM25 + vector search engine with RRF fusion, persisted corpus statistics, quality/abstention gates, rescue tiers, and match-boost reranking."
resource: code_search/engine/search.py
tags: [engine, search, ranking, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Implements hybrid search combining BM25 keyword retrieval (sparse,
lexical) and vector semantic search (dense) using Reciprocal Rank Fusion
(RRF). This is the core search engine layer of code-search, providing
ranked, exhaustive (line-wise), and enumerate (symbol-list) modes. Three
layers separate concerns: [`BM25Search`](../../types/BM25Search.md) (FTS5
keyword retrieval), [`VectorSearch`](../../types/VectorSearch.md) (semantic
embedding lookups), and [`HybridSearch`](../../types/HybridSearch.md)
(orchestrates the full pipeline with quality gates, rescue tiers,
match-boost overlays, and reranking signals such as symbol resolution,
file-stem rescue, authorization intent, and config scent).

When no explicit `content` scope is supplied, the default is inferred from
[`classify_content_intent`](../../functions/classify_content_intent.md): a
code-shaped query defaults to `code`, a docs-shaped query to `all`, and
other queries to `code_focused`, so config/build files cannot outrank
source on shared vocabulary. The CLI, MCP, and daemon pass
`include_tests=False` by default (the engine method still defaults to
`True`); lexical match counts are split into `production_matches` and
`test_matches`, with `total_matches` covering both. Scores are reported as ordered evidence, not
probabilities: each result carries `score_normalized` plus
`token_savings` at the envelope level. Exhaustive mode accepts an optional
regular expression (`regex=True`).

Corpus document frequencies come from the persisted `subword_stats` and
`prefix_stats` tables when the index provides them: `token_doc_counts` and
`prefix_doc_counts` fetch only the queried rows, and `present_terms`
answers vocabulary membership without loading every chunk's `subwords`.
Indexes that predate the statistics (or hand-built test databases) fall
back to the full `code_chunks.subwords` scan, so correctness never depends
on the migration having run.

The post-rank abstention gate compares concept coverage and top-vs-median
score separation against `abstention_coverage_min` and
`abstention_separation_min`; `allow_weak=True` (CLI `--allow-weak`) bypasses
that gate for callers that prefer weak evidence over an empty answer.
`strict=True` is the opposite posture: a low-confidence ranked pool with no
definition hit and informative coverage below `exact_token_coverage_min`
becomes a `no_match` envelope, with the weak rows preserved under
`alternatives` so the caller still sees what was rejected
(`_strict_abstention`). `_informative_coverage` computes the fraction of
informative query sub-words present in the top rows.

Exhaustive literal search runs through `rg --json` when `rg` is available
(`_ripgrep_path`, `_ripgrep_literal`, per-batch deadline
`CODE_SEARCH_EXHAUSTIVE_RG_TIMEOUT_S`) and falls back to the in-process scan
(`_read_indexed_file`) on a missing binary or a timeout, so a slow backend
never yields a partial count. Path-shape signals read the repo-relative
spelling from `_signal_path`, and a cold vector model is given one bounded
chance to warm (`_cold_model_retry_worthwhile`, `_wait_for_cold_model`) before
the reduced lexical answer is served.

# Key Constants

| Constant | Purpose |
|---|---|
| `DEFAULT_CONTENT_SCOPE` | Default content axis, `"code_focused"` |
| `VALID_CONTENT_SCOPES` | `("code", "config", "docs", "all", "code_focused")` |
| `VALID_MATCHING_SEMANTICS` | `("literal", "all_tokens", "any_token")` for exhaustive mode |
| `STOPWORDS` | 94 English stopwords removed by optional filter |
| `NON_INFORMATIVE_CODE_TERMS` | 118 language keywords excluded from informative-token coverage |

# Key Classes

- [`BM25Search`](../../types/BM25Search.md) — FTS5-based BM25 keyword search over the indexed corpus.
- [`VectorSearch`](../../types/VectorSearch.md) — semantic search using the vector index.
- [`HybridSearch`](../../types/HybridSearch.md) — combines both via RRF fusion, with quality gates, rescue ladder, and match-boost.

# Key Functions

- [`tokenize`](../../functions/tokenize.md), [`identify_subwords`](../../functions/identify_subwords.md), [`decompose_query`](../../functions/decompose_query.md) — tokenization and identifier decomposition.
- [`build_fts_query`](../../functions/build_fts_query.md) — build an FTS5 MATCH expression from decomposed sub-words.
- [`query_symbol_identifier`](../../functions/query_symbol_identifier.md), [`classify_query`](../../functions/classify_query.md) — classify a query as symbol-like or natural-language.
- [`exact_precheck`](../../functions/exact_precheck.md) — detect concrete literal/annotation/identifier patterns in a query.
- [`chunk_rank_class`](../../functions/chunk_rank_class.md) — classify a chunk as code/boilerplate/resource.
- [`rrf_fusion`](../../functions/rrf_fusion.md) — Reciprocal Rank Fusion of BM25 and vector result lists.

# Internal Helpers

`HybridSearch` carries dozens of private methods implementing the ranking
pipeline stages: query-quality gating (`_query_quality_gate`), stem rescue
(`_stem_rescue`), embedded-symbol pass (`_embedded_symbol_pass`),
match-boost (`_match_boost_pass`), authorization/config/DDL/migration
scent detection, the rescue ladder (`_rescue_envelope`, `_rescue_t1`,
`_rescue_t2`), exhaustive/enumerate mode implementations
(`_search_exhaustive`, `_search_enumerate`), and file coherence
(`_apply_file_coherence`). Two passes added after the match-boost layer
lift definitions by intent: `_symbol_concept_pass` boosts (and can inject)
definitions whose symbol name carries the query's rare concept terms,
weighted by inverse pool frequency (`_concept_match_terms`,
`_concept_term_weights`, `_leader_matches_concept`), and
`_endpoint_intent_pass` boosts controller methods annotated for the verb
named in an endpoint query (`_HTTP_METHOD_ANNOTATIONS`, `_ENDPOINT_WORDS`).
Both emit evidence consumed by the confidence floors in
[`engine.confidence`](confidence.md) and are controlled by the
`CODE_SEARCH_CONCEPT_SYMBOL_*` and `CODE_SEARCH_ENDPOINT_INTENT_*`
settings. `_concept_matches` matches a term to a symbol sub-word exactly or
by a shared prefix whose length differs by at most three characters.
`_constant_intent_pass` lifts constant/config declarations for
constant-shaped queries such as "default page size" (controlled by
`CODE_SEARCH_CONSTANT_INTENT_*`), while `_code_intent` infers the code
content scope. `_count_test_matches` (with the cached
`_cached_test_file_paths`) produces the production/test match split, and
`_token_savings` estimates the tokens an agent avoids reading in full
files. `_search_exhaustive` supports regular-expression matching when
`regex=True`.
