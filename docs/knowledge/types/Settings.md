---
type: Class
title: "Settings"
description: "Central configuration dataclass with 176 CODE_SEARCH_* environment-variable-backed fields, platform-derived defaults, and runtime-profile presets."
resource: code_search/engine/config.py#Settings
tags: [config, settings, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/config.py
    id: source-code
---

# Overview

Central configuration dataclass with 176 fields, each overridable via a
`CODE_SEARCH_*` environment variable. Loaded once via `Settings.from_env()`
and threaded through nearly every engine component. `runtime_profile`
(`standard`/`small`) supplies defaults for `index_layout`
(`legacy`/`compact`) and `freshness_mode` (`blocking`/`deferred`); an
explicit environment variable or CLI flag always wins. Defined in
[`engine.config`](../modules/engine/config.md). The full field list is
documented in [config/environment.md](../config/environment.md); this
concept summarises the major field groups.

# Schema (representative groups)

| Group | Example fields | Description |
|---|---|---|
| Core | `context_dir`, `log_level`, `data_dir`, `model_path` | Filesystem locations and logging verbosity. |
| Embedding model | `embedding_model`, `embedding_dim`, `model_profile`, `fast_embedding_model` | Model2Vec embedding configuration. |
| Cold start | `warmup_wait_s`, `startup_wait_s` | Bounded waits for the embedding model and for a freshly spawned daemon. |
| Content-type classification | `config_content_boost`, `docs_content_boost`, `config_scent_words` | Score multipliers for config/docs-scented queries. |
| Canonicality tiers | `docs_project_boost`, `docs_third_party_penalty`, `docs_generated_penalty`, `docs_inject_boost`, `config_primary_boost`, `config_nonprimary_penalty` | Docs/config canonicality multipliers. |
| Corpus hygiene | `minified_penalty`, `vendor_penalty`, `module_cohesion_boost` | Demote minified/vendored assets and prefer path-segment module matches. |
| Runtime profile | `runtime_profile`, `index_layout`, `freshness_mode`, `max_file_bytes`, `index_graph` | Profile presets, vector layout, freshness strategy, indexer size cap, and graph persistence. |
| Abstention | `abstention_coverage_min`, `abstention_separation_min` | Post-rank abstention gate thresholds. |
| BM25 / lexical search | `bm25_k1`, `bm25_b`, `bm25_content_weight`, `bm25_fqn_weight` | FTS5 BM25 lexical-ranking tuning parameters. |
| Vector / fusion | `min_vector_cosine`, `rrf_k`, `max_results`, `search_top_k_multiplier` | Vector similarity thresholds and rank-fusion parameters. |
| Query-quality gate | `relevance_gate`, `idf_floor`, `informative_tokens_min`, `concept_signal_min` | Thresholds for the multi-signal quality gate. |
| Trust signals | `exact_token_coverage_min`, `top_vector_floor`, `exact_match_boost` | Exact-match and vector-trust thresholds. |
| Confidence | `confidence_high_floor`, `confidence_medium_floor` | Calibrated confidence band boundaries. |
| Reranking | `definition_boost`, `identifier_definition_boost`, `identifier_usage_penalty`, `config_key_boost`, `noise_penalty`, `non_canonical_penalty` | Post-fusion reranking weights, including identifier-definition and config-key precedence. |
| Session | `session_ttl_hours`, `decay_constant`, `session_read_weight` | Session-based personalisation decay parameters. |
| Indexing / watcher / graph | `respect_gitignore`, `lock_timeout`, `max_chunk_lines`, `watch_poll_interval`, `max_graph_depth`, `index_doc_links`, `doc_link_top_k` | Indexing, `.gitignore` handling, doc-link computation, file-watch, and graph-traversal limits. |
| Match-boost layer | `match_boost_enabled`, `match_boost_cap`, `match_boost_exact_fqn` | Bounded additive name-match boosting. |
| Concept-symbol pass | `concept_symbol_boost`, `concept_symbol_anchor_boost`, `concept_symbol_min_ratio`, `concept_symbol_pool_max_share` | Symbol-name concept matching for natural-language queries. |
| Endpoint-intent pass | `endpoint_intent_boost`, `endpoint_intent_cap` | HTTP-verb annotated controller-method boosting. |
| Constant-intent pass | `constant_intent_boost`, `constant_intent_cap`, `constant_intent_words` | Lifts constant/config declarations for default/constant-shaped queries. |
| Rescue ladder | `rescue_t1_enabled`, `rescue_literal_enabled` | Tiered rescue thresholds. |

# Methods

| Method | Description |
|---|---|
| `from_env() -> Settings` | Build `Settings` from `CODE_SEARCH_*` environment variables. |
| `resolve_embedding_profile() -> tuple[str, int]` | Resolve the selected model profile to an `(embedding_model, dim)` pair. |
| `with_context_dir(context_dir: Path \| None) -> Settings` | Build `Settings` with an explicit context directory override. |
| `resolve_context_dir() -> Path` | Return the absolute, created context directory path. |
| `profile_reason() -> str` | Explain how the effective layout and freshness mode were chosen, naming the profile and any explicit overrides. |
| `with_repo_expansions() -> Settings` | Return settings that prefer a repository's own `.code-search/expansions.json` pack, unless an explicit `CODE_SEARCH_EXPANSION_FILE` already chose one. |
