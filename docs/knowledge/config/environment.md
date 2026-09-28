---
type: Overview
title: "Environment Configuration"
description: "Full enumeration of CODE_SEARCH_* environment variables backing the Settings dataclass."
resource: src/engine/config.py
tags: [config, environment, settings]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

All runtime configuration for `code-search` is read from `CODE_SEARCH_*`
environment variables at process start, via the [`Settings`](/types/Settings.md)
dataclass ([`engine.config`](/modules/engine/config.md)). There is no
config file for these values (a separate `CODE_SEARCH_LANGUAGE_CONFIG`
path controls per-language parsing settings via
[`LanguageConfig`](/types/LanguageConfig.md) instead). Booleans accept
`true`/`1`/`yes` (case-insensitive) unless noted.

# Core Paths

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_CONTEXT_DIR` | `.context` | Root directory for the index, vector store, and graph database. |
| `CODE_SEARCH_LOG_LEVEL` | `WARNING` | Logging verbosity for the engine and CLI. |
| `CODE_SEARCH_DATA_DIR` | (none) | Overrides the data directory used to locate bundled model assets. |
| `CODE_SEARCH_MODEL_PATH` | (none) | Explicit override path to a local embedding model directory. |
| `CODE_SEARCH_LANGUAGE_CONFIG` | `language_config.json` | Path to the per-language parsing config consumed by [`LanguageConfig`](/types/LanguageConfig.md). |

# Embedding Model

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_EMBEDDING_MODEL` | `potion-code-16m-32d` | Model2Vec model name/path used for chunk embeddings. |
| `CODE_SEARCH_EMBEDDING_DIM` | `32` | Expected embedding vector dimensionality. |
| `CODE_SEARCH_MODEL_PROFILE` | `default` | `default` or opt-in `fast` profile; switching profiles changes the vector space and requires a re-index. |
| `CODE_SEARCH_FAST_EMBEDDING_MODEL` | `potion-base-2M` | Model used when `model_profile=fast`. |
| `CODE_SEARCH_FAST_EMBEDDING_DIM` | `64` | Embedding dimensionality for the fast profile. |
| `CODE_SEARCH_EMBED_TEXT_MAX_CHARS` | `2000` | Max characters of enclosing-context + chunk content passed to the embedding model. |

# Relevance Threshold

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_RELEVANCE_THRESHOLD` | `0.05` | Minimum fused score for a result to be considered relevant. |
| `CODE_SEARCH_RANKED_SCORE_FLOOR` | `0.05` | Minimum top fused score required for ranked mode to return results instead of `no_match`. |

# Resource / Content Handling

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_RESOURCE_EXTENSIONS` | (built-in list) | Comma-separated file extensions treated as non-code "resource" files. |
| `CODE_SEARCH_INDEX_PROSE` | `true` | Whether prose/docs files are indexed at all. |

# Content-Type Classification

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_CONFIG_CONTENT_BOOST` | `1.35` | Score multiplier for config-classified chunks on a config-scented query. |
| `CODE_SEARCH_CONFIG_INJECT_BOOST` | `0.75` | Multiplier applied when injecting config chunks into results. |
| `CODE_SEARCH_CONFIG_INJECT_PRIMARY_EXTRA` | `0.3` | Extra boost for the primary injected config chunk. |
| `CODE_SEARCH_DOCS_CONTENT_BOOST` | `1.2` | Score multiplier for docs-classified chunks. |
| `CODE_SEARCH_NON_CODE_LANGUAGE_DEMOTE` | `0.7` | Demotion multiplier for config/docs chunks under an active code-language query context. |
| `CODE_SEARCH_CONFIG_SCENT_WORDS` | (built-in list) | Vocabulary that triggers config-scent detection. |
| `CODE_SEARCH_EXHAUSTIVE_MATCHING_MODE` | `all_tokens` | `all_tokens` (AND) or `any_token` (OR) line-matching semantics. |
| `CODE_SEARCH_BORDERLINE_FILTER` | `false` | Drop low-confidence-band results instead of tagging them. |
| `CODE_SEARCH_FIND_RELATED_EXCLUDE_FILE` | `true` | Exclude the anchor chunk's own file from `find_related` neighbors. |
| `CODE_SEARCH_FIND_RELATED_SAME_FILE_PENALTY` | `0.5` | Down-weight applied to same-file neighbors when exclusion is off. |
| `CODE_SEARCH_CAPTURE_UNRESOLVED_CALLEES` | `true` | Persist unresolved callee references as `resolved: false` edges. |
| `CODE_SEARCH_SCAFFOLD_TOPIC_WORDS` | (built-in list) | Query words that lift the scaffolding demotion for on-topic scaffolding. |

# BM25 / Lexical Search

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_MIN_VECTOR_COSINE` | `0.25` | Minimum cosine similarity for a vector hit to count. |
| `CODE_SEARCH_BM25_K1` | `1.5` | BM25 term-frequency saturation parameter. |
| `CODE_SEARCH_BM25_B` | `0.75` | BM25 length-normalization parameter. |
| `CODE_SEARCH_BM25_CONTENT_WEIGHT` | `1.0` | Weight of the content field in the FTS5 query. |
| `CODE_SEARCH_BM25_SUBWORDS_WEIGHT` | `0.6` | Weight of the subwords field. |
| `CODE_SEARCH_BM25_FQN_WEIGHT` | `0.5` | Weight of the fully-qualified-name field. |
| `CODE_SEARCH_BM25_PATH_WEIGHT` | `0.2` | Weight of the file path field. |
| `CODE_SEARCH_BM25_RULES_WEIGHT` | `0.4` | Weight of the declared-rules field. |
| `CODE_SEARCH_RRF_K` | `60` | Reciprocal Rank Fusion constant. |
| `CODE_SEARCH_MAX_RESULTS` | `50` | Maximum results returned per search. |
| `CODE_SEARCH_TOP_K_MULTIPLIER` | `2` | Multiplier applied to top-k when building the candidate pool. |
| `CODE_SEARCH_CANDIDATE_POOL_MIN` | `40` | Minimum candidate pool size before fusion. |
| `CODE_SEARCH_FILTER_STOPWORDS` | `false` | Strip stopwords from the query before lexical search. |

# Query-Quality Gate

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_RELEVANCE_GATE` | `true` | Enables the multi-signal quality gate before returning ranked results. |
| `CODE_SEARCH_IDF_FLOOR` | `0.8` | Minimum IDF for a token to count as informative. |
| `CODE_SEARCH_INFORMATIVE_TOKENS_MIN` | `1` | Minimum informative tokens required to pass the gate. |
| `CODE_SEARCH_CONCEPT_SIGNAL_MIN` | `2` | Minimum concept-signal strength required to pass the gate. |
| `CODE_SEARCH_VECTOR_ONLY_COSINE_FLOOR` | `0.5` | Minimum cosine similarity accepted for vector-only matches. |

# Trust Signals

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_EXACT_TOKEN_COVERAGE_MIN` | `0.5` | Minimum fraction of query tokens that must appear verbatim. |
| `CODE_SEARCH_TOP_VECTOR_FLOOR` | `0.5` | Minimum top vector score to trust vector-only evidence. |
| `CODE_SEARCH_EXPANSION_FILE` | `""` | Path to a custom query-expansion synonym file. |
| `CODE_SEARCH_EXACT_MATCH_BOOST` | `0.5` | Boost applied when a query token exactly matches indexed content. |
| `CODE_SEARCH_LANGUAGE_SCOPE_MODE` | `demote` | How out-of-scope-language results are treated (`demote` vs. exclude). |
| `CODE_SEARCH_LANGUAGE_SCOPE_PENALTY` | `0.5` | Penalty multiplier applied under `demote` mode. |

# Rank-Class Weights

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_RESOURCE_DEBOOST` | `0.35` | Score multiplier for resource-classified chunks. |
| `CODE_SEARCH_BOILERPLATE_DEBOOST` | `0.65` | Score multiplier for boilerplate-classified chunks. |
| `CODE_SEARCH_MIN_LIFT` | `0.05` | Minimum score lift required to promote a demoted chunk back up. |
| `CODE_SEARCH_RESOURCE_INTENT_WORDS` | (built-in list) | Query words indicating deliberate resource-file intent. |

# Exact Pre-Check / Score Breakdown / Confidence

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_EXACT_PRECHECK_TAGS` | `on` | Enables the exact-match pre-check pass. |
| `CODE_SEARCH_SCORE_BREAKDOWN` | `true` | Include per-signal score breakdown in responses. |
| `CODE_SEARCH_CONFIDENCE_HIGH_FLOOR` | `0.7` | Calibrated score at/above this is the `high` confidence band. |
| `CODE_SEARCH_CONFIDENCE_MEDIUM_FLOOR` | `0.45` | Calibrated score at/above this (below high) is `medium`; below is `low`. |

# File Coherence, Scent, Suggestions, Reranking

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_COHERENCE_BONUS` | `0.05` | Bonus for chunks whose file has multiple coherent matches. |
| `CODE_SEARCH_CONFIG_SCENT_BOOST` | `1.5` | Boost for config-scented query matches. |
| `CODE_SEARCH_DDL_SCENT_BOOST` | `1.8` | Boost for DDL-scented query matches. |
| `CODE_SEARCH_SUGGEST_EDIT_DISTANCE` | `2` | Max edit distance for symbol "did you mean" suggestions. |
| `CODE_SEARCH_DEFINITION_BOOST` | `1.2` | [`Reranker`](/types/Reranker.md) boost for definition chunks. |
| `CODE_SEARCH_NOISE_PENALTY` | `0.5` | Reranker penalty for noisy/test-like chunks. |
| `CODE_SEARCH_NON_CANONICAL_PENALTY` | `0.25` | Reranker penalty for non-canonical duplicate definitions. |

# Session-Based Personalization

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_SESSION_TTL_HOURS` | `24` | Session record time-to-live. |
| `CODE_SEARCH_DECAY_CONSTANT` | `0.1` | Exponential decay constant applied to session weighting. |
| `CODE_SEARCH_SESSION_WRITE_WEIGHT` | `1.0` | Weight given to files the session has written. |
| `CODE_SEARCH_SESSION_READ_WEIGHT` | `0.7` | Weight given to files the session has read. |
| `CODE_SEARCH_GIT_TIMEOUT` | `10` | Timeout (seconds) for git subprocess calls used in session context. |

# Indexing, Watcher, Freshness, Graph, Metrics

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_LOCK_TIMEOUT` | `30.0` | Timeout for acquiring the index lock. |
| `CODE_SEARCH_MAX_CHUNK_LINES` | `100` | Maximum lines per indexed chunk. |
| `CODE_SEARCH_WATCH_DEBOUNCE` | `1.0` | Debounce window (seconds) for [`FileWatcher`](/types/FileWatcher.md). |
| `CODE_SEARCH_WATCH_POLL_INTERVAL` | `1.0` | Polling interval (seconds) for the file watcher. |
| `CODE_SEARCH_FRESHNESS_TTL_SECONDS` | `5.0` | Cache TTL for computed freshness signals; `0` disables caching. |
| `CODE_SEARCH_MAX_GRAPH_DEPTH` | `5` | Maximum traversal depth for call-graph queries. |
| `CODE_SEARCH_CALL_GRAPH_LIMIT` | `50` | Maximum nodes returned per call-graph query. |
| `CODE_SEARCH_MAX_RESOLUTION_CANDIDATES` | `10` | Maximum candidates considered when resolving a symbol reference. |
| `CODE_SEARCH_METRICS_WINDOW_SIZE` | `1000` | Rolling window size for [`MetricsCollector`](/types/MetricsCollector.md) latency percentiles. |

# MCP Server / Display

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_FIND_RELATED_LIMIT` | `100` | Max neighbors returned by the `find_related` MCP tool. |
| `CODE_SEARCH_QUERY_SUMMARY_LENGTH` | `100` | Max characters of query text echoed back in summaries. |
| `CODE_SEARCH_SNIPPET_LENGTH` | `60` | Max characters of a result snippet shown to the user. |

# Search-Quality Knobs

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_CHUNK_TARGET_CHARS` | `750` | Target chunk size (characters) during chunking. |
| `CODE_SEARCH_CHUNK_MIN_CHARS` | `50` | Minimum chunk size before merging with a neighbor. |
| `CODE_SEARCH_STEM_RESCUE_BOOST` | `1.0` | Boost applied during stem-based rescue. |
| `CODE_SEARCH_STEM_MATCH_BOOST` | `1.5` | Boost for filename-stem matches. |
| `CODE_SEARCH_ALPHA_SYMBOL` | `0.3` | Weight of symbol-name similarity in blended scoring. |
| `CODE_SEARCH_ALPHA_NL` | `0.5` | Weight of natural-language similarity in blended scoring. |
| `CODE_SEARCH_STEM_MIN_PREFIX` | `3` | Minimum prefix length for stem matching. |
| `CODE_SEARCH_NL_BOOST_MAX` | `1.0` | Cap on the natural-language boost. |
| `CODE_SEARCH_NL_BOOST_KEYWORDS_MIN` | `2` | Minimum keyword overlap to apply the NL boost. |
| `CODE_SEARCH_EMBEDDED_SYMBOL_BOOST` | `0.5` | Boost for chunks containing an embedded symbol match. |
| `CODE_SEARCH_DTS_PENALTY` | `0.7` | Penalty for `.d.ts`-style declaration files. |
| `CODE_SEARCH_BARREL_PENALTY` | `0.5` | Penalty for barrel/re-export files. |

# Match-Boost Layer

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_MATCH_BOOST_ENABLED` | `true` | Enables the additive [`BoostVerdict`](/types/BoostVerdict.md) layer. |
| `CODE_SEARCH_MATCH_BOOST_CAP` | `2.0` | Upper bound on total per-chunk match boost. |
| `CODE_SEARCH_MATCH_BOOST_EXACT_FQN` | `2.0` | Boost multiplier for exact FQN match. |
| `CODE_SEARCH_MATCH_BOOST_EXACT_SYMBOL` | `1.5` | Boost multiplier for exact symbol match. |
| `CODE_SEARCH_MATCH_BOOST_EXACT_FILENAME` | `1.5` | Boost multiplier for exact filename match. |
| `CODE_SEARCH_MATCH_BOOST_STEM` | `0.5` | Boost multiplier for filename-stem/parent-directory match. |
| `CODE_SEARCH_MATCH_BOOST_GENERIC_STEMS` | (built-in list) | Ubiquitous stems (e.g. `config`, `main`, `index`) dampened to avoid false crowning. |

# Query Intent Scope Inference

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_INTENT_SCOPE_ENABLED` | `true` | Allows a docs-shaped query with no explicit scope to retry under `all` scope on empty results. |

# Rescue Ladder

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_RESCUE_T1_ENABLED` | `true` | Enables tier-1 rescue (relaxed quality gate). |
| `CODE_SEARCH_RESCUE_T1_INFORMATIVE_TOKENS_MIN` | `1` | Relaxed informative-token minimum for T1. |
| `CODE_SEARCH_RESCUE_T1_CONCEPT_SIGNAL_MIN` | `1` | Relaxed concept-signal minimum for T1. |
| `CODE_SEARCH_RESCUE_T1_RELEVANCE_THRESHOLD` | `0.0` | Relaxed relevance threshold for T1. |
| `CODE_SEARCH_RESCUE_LITERAL_ENABLED` | `true` | Enables tier-2 rescue (literal case-insensitive substring scan). |

# Definition-Owner / Model-File Reranking, Declared-Rule Boost, Infra Demotion

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_DEFINITION_OWNER_BOOST` | `1.5` | Boost for a symbol's own definition chunk on definition-intent queries. |
| `CODE_SEARCH_MODEL_FILE_PENALTY` | `0.6` | Penalty for model/DTO/exception plumbing files on behavior-intent queries. |
| `CODE_SEARCH_DEFINITION_INTENT_WORDS` | (built-in list) | Vocabulary indicating a "where is X defined" query. |
| `CODE_SEARCH_BEHAVIOR_INTENT_WORDS` | (built-in list) | Vocabulary indicating a "how is X used" query. |
| `CODE_SEARCH_DECLARED_RULE_BOOST` | `1.5` | Boost for chunks matching a declared-rule intent query. |
| `CODE_SEARCH_DECLARED_RULE_INTENT_WORDS` | (built-in list) | Vocabulary indicating a declared-rule query. |
| `CODE_SEARCH_INFRA_DEBOOST` | `0.35` | Demotion for infrastructure/plumbing files. |
| `CODE_SEARCH_INFRA_DEBOOST_RELAXED` | `0.5` | Relaxed demotion used under rescue tiers. |

# Intent Vocabularies and Find-Related Weights

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_AUTHORIZATION_INTENT_WORDS` | (built-in list) | Vocabulary for authorization-intent queries. |
| `CODE_SEARCH_DDL_INTENT_WORDS` | (built-in list) | Vocabulary for DDL-intent queries. |
| `CODE_SEARCH_MIGRATION_INTENT_WORDS` | (built-in list) | Vocabulary for migration-intent queries. |
| `CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS` | `reports,analysis,benchmarks` | Path fragments identifying generated analysis artifacts. |
| `CODE_SEARCH_FIND_RELATED_EXCLUDE_BOILERPLATE` | `true` | Excludes boilerplate-classified chunks from `find_related`. |
| `CODE_SEARCH_FIND_RELATED_WEIGHT_PACKAGE` | `0.2` | Weight of package-overlap signal in `find_related` scoring. |
| `CODE_SEARCH_FIND_RELATED_WEIGHT_TYPE` | `0.2` | Weight of type-sharing signal. |
| `CODE_SEARCH_FIND_RELATED_WEIGHT_CALL_GRAPH` | `0.6` | Weight of call-graph proximity signal. |
| `CODE_SEARCH_FIND_RELATED_SEMANTIC_BLEND` | `0.8` | Blend factor between semantic similarity and structural signals. |

# Exhaustive Mode and Enumerate Mode

| Variable | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_EXHAUSTIVE_ENABLED` | `true` | Enables exhaustive (every-matching-line) search mode. |
| `CODE_SEARCH_EXHAUSTIVE_MAX_LINES` | `1000` | Max lines scanned/returned in exhaustive mode. |
| `CODE_SEARCH_EXHAUSTIVE_CASE_SENSITIVE` | `true` | Case sensitivity for exhaustive-mode matching. |
| `CODE_SEARCH_ENUMERATE_ENABLED` | `true` | Enables enumerate (list-all-instances) mode. |
| `CODE_SEARCH_ENUMERATION_INTENT_WORDS` | (built-in list) | Vocabulary that triggers enumerate-mode detection. |

# See Also

- [`Settings`](/types/Settings.md) — the dataclass these variables populate.
- [Build System](/config/build-system.md)
