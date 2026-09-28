---
type: Class
title: "HybridSearch"
description: "Combines BM25 keyword search and vector semantic search via RRF fusion, with quality gates and rescue tiers."
resource: src/engine/search.py#HybridSearch
tags: [search, ranking, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Combines BM25 keyword search and vector semantic search via RRF fusion.
Supports filtering by language, exclusion of test files, and automatic
degradation to BM25-only when the vector model is unavailable. Defined in
[`engine.search`](/modules/engine/search.md); this is the central
orchestrator of the search pipeline.

# Public Methods

| Method | Description |
|---|---|
| `__init__(self, db, vector_index, embedding_generator, settings=None, no_model=False) -> None` | Initialize hybrid search; `no_model=True` runs the fast BM25-only path. |
| `search(self, query: str, limit: int = 10, language: str \| None = None, include_tests: bool = True, alpha: float \| None = None, mode: str = "ranked", content: str \| None = None, matching: str \| None = None) -> dict[str, Any]` | Run the full hybrid search pipeline; the single public entry point. Stamps `query_time_ms`, `model_status`, `degraded_reason`, `ranked_path`, and `scope`. |
| `invalidate_bm25_corpus() -> None` | Invalidate cached BM25 corpus statistics after re-indexing. |
| `reset_caches() -> None` | Reset internal caches after index rebuild. |
| `need_index() -> bool` | Return whether the index has not reached the `"ready"` state. |

# Internal Pipeline (private methods)

`search()` delegates to `_search_impl`, which runs: query analysis
(`_build_query_match_context`, `_build_query_name_context`), BM25 +
vector retrieval, test-file demotion, RRF fusion (`rrf_fusion`), the
multi-signal quality gate (`_query_quality_gate`), stem rescue
(`_stem_rescue`), embedded-symbol pass (`_embedded_symbol_pass`),
authorization/config/DDL/migration scent injection, the bounded
match-boost layer (`_match_boost_pass`), file coherence
(`_apply_file_coherence`), and — when the ranked path is empty — the
rescue ladder (`_rescue_envelope` → `_rescue_t1` → `_rescue_t2`).
Exhaustive (`_search_exhaustive`) and enumerate (`_search_enumerate`)
modes bypass ranking entirely.
