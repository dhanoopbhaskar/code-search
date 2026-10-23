---
type: Class
title: "HybridSearch"
description: "Combines BM25 keyword search and vector semantic search via RRF fusion, with quality gates and rescue tiers."
resource: code_search/engine/search.py#HybridSearch
tags: [search, ranking, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Combines BM25 keyword search and vector semantic search via RRF fusion.
Supports filtering by language, exclusion of test files, and automatic
degradation to BM25-only when the vector model is unavailable. Defined in
[`engine.search`](../modules/engine/search.md); this is the central
orchestrator of the search pipeline.

# Public Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, vector_index: VectorIndex, embedding_generator: EmbeddingGenerator, settings: Settings \| None = None, no_model: bool = False) -> None` | Initialize hybrid search over the graph DB and vector index. |
| `search(query: str, limit: int = 10, language: str \| None = None, include_tests: bool = True, alpha: float \| None = None, mode: str = 'ranked', content: str \| None = None, matching: str \| None = None, regex: bool = False, allow_weak: bool = False) -> dict[str, Any]` | Run the full hybrid search pipeline and stamp the per-request timer; *regex* switches ranked/exhaustive scanning to regular-expression matching, and *allow_weak* bypasses the post-rank abstention gate. |
| `token_doc_counts(tokens: set[str]) -> dict[str, int]` | Return `token -> distinct chunk count` from `subword_stats` for only the requested tokens. |
| `prefix_doc_counts(prefixes: set[str]) -> dict[str, int]` | Return `prefix -> distinct chunk count` from `prefix_stats` for only the requested prefixes. |
| `present_terms(tokens: set[str]) -> set[str]` | Return the subset of tokens present in the corpus, using persisted stats when available. |
| `invalidate_bm25_corpus() -> None` | Invalidate the cached BM25 corpus statistics after re-indexing. |
| `reset_caches() -> None` | Reset internal caches after an index rebuild. |
| `need_index() -> bool` | Return whether the index has not reached the `ready` state. |

# Internal Pipeline (private methods)

| Method | Description |
|---|---|
| `_vector_layer_health() -> bool` | Return whether the vector layer is genuinely usable for this query. |
| `_resolve_semantic_report(chunk_id: int, raw_vector_map: dict[int, float], *, vector_health: bool, defer_vector: bool, model_warm: bool, lexical_only_query: bool) -> tuple[float, bool, str]` | Resolve a result's truthful vector score and contribution label. |
| `_demote_test_file_candidates(bm25_results: list[tuple[int, float]], vector_results: list[tuple[int, float]]) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]` | Demote test-file chunks inside the candidate pool (pre-fusion). |
| `_build_analysis(query: str, explicit_language: str \| None = None) -> QueryAnalysis` | Build the query-analysis entity once per search. |
| `_vocab_from_db() -> set[str]` | Exact sub-word vocabulary straight from `code_chunks`. |
| `_stamp_model_status(envelope: dict[str, Any], was_warm: bool) -> None` | Stamp `ranked_path`, `warmup_state`, `model_status` on ranked envelopes. |
| `_search_impl(query: str, limit: int = 10, language: str \| None = None, include_tests: bool = True, alpha: float \| None = None, mode: str = 'ranked', content: str \| None = None, matching: str \| None = None, regex: bool = False) -> dict[str, Any]` | Run the full hybrid search pipeline for *query*. |
| `_token_savings(results: list[dict[str, Any]]) -> dict[str, Any]` | Estimate agent token savings (`files`, `returned_tokens`, `full_file_tokens`, `saved_tokens`, `saved_percent`) at 4 characters per token. |
| `_constant_intent_pass(query: str, fused: dict[int, float], content: str) -> dict[int, dict[str, Any]]` | Lift the config/constant chunks that define a query's named constant (`CODE_SEARCH_CONSTANT_INTENT_*`) and return per-chunk evidence. |
| `_code_intent(query: str, explicit_language: str \| None) -> bool` | Return whether the query is a fuzzy source-level (code-intent) search. |
| `_cached_test_file_paths() -> list[str]` | Cached variant of `_test_file_paths`. |
| `_count_test_matches(query: str, content: str) -> int` | Count FTS5-matching chunks restricted to test files, for the production/test split. |
| `_build_query_match_context(query: str) -> QueryMatchContext` | Build the query-level match context once per request. |
| `_is_bare_symbol_token(query: str) -> bool` | Return whether *query* is a single identifier-like token. |
| `_build_query_name_context(query: str, match_context: QueryMatchContext \| None = None) -> QueryNameContext` | Build the request-scoped name context once per query. |
| `_identifier_is_ambiguous(identifier: str) -> bool` | Return whether *identifier* resolves to distinct same-named symbols. |
| `_exact_filename_candidates(name_context: QueryNameContext, content: str, bm25_results: list[tuple[int, float]], raw_vector_results: list[tuple[int, float]]) -> tuple[int, ...]` | Return exact-filename candidate chunk ids for the request. |
| `_match_boost_weights() -> dict[MatchTier, float]` | Return the per-tier weight map for the match-boost layer. |
| `_is_demoted_chunk_path(file_path: str, analysis_paths: set[str]) -> bool` | Return whether *file_path* is a demoted (non-production) role. |
| `_exact_symbol_rows(name_context: QueryNameContext) -> list[Any]` | Return definition-chunk rows matching the query's symbol name. |
| `_match_boost_pass(name_context: QueryNameContext, exact_filename_ids: tuple[int, ...], fused: dict[int, float]) -> dict[int, dict[str, Any]]` | Apply the bounded match-boost layer to the fused pool. |
| `_resolve_bare_symbol(identifier: str) -> str \| None` | Return the canonical FQN when *identifier* resolves exactly. |
| `_resolved_symbol_name() -> str \| None` | Return the short name of the symbol a symbol-intent query resolves. |
| `_symbol_stem(symbol_name: str) -> str` | Return the lowercased leading sub-word of *symbol_name*. |
| `_resolve_alpha(alpha: float \| None) -> float` | Resolve the blend weight for the current query. |
| `_pool_max(fused: dict[int, float]) -> float` | Return the highest fused score, falling back to 1.0 for an empty pool. |
| `_definition_chunks(symbol_names: list[str]) -> dict[str, list[Any]]` | Return the `is_definition = 1` chunks named by *symbol_names*. |
| `_stem_rescue(fused: dict[int, float], symbol_name: str) -> dict[int, dict[str, Any]]` | Lift definition chunks whose file stem relates to the symbol stem. |
| `_embedded_symbol_pass(query: str, fused: dict[int, float]) -> tuple[dict[int, Any], dict[int, dict[str, Any]]]` | Lift definition chunks of symbols named in natural-language prose. |
| `_symbol_reference_inject(fused: dict[int, float], symbol_name: str) -> None` | Inject definition chunks of a bare ambiguous partial symbol reference. |
| `_nl_path_boost(name_context: QueryNameContext, top_chunk_ids: list[int], chunk_map: dict[int, dict[str, Any]], fused: dict[int, float], skip_ids: frozenset[int] = frozenset()) -> tuple[dict[int, float], dict[int, dict[str, Any]]]` | Boost chunks whose file path prefix-matches NL query keywords. |
| `_detect_exact_precheck(query: str) -> dict[str, Any] \| None` | Return the exact pre-check descriptor, honoring the toggle. |
| `_resource_intent(query: str) -> bool` | Return whether *query* carries explicit resource intent. |
| `_class_weights(resource_intent: bool) -> dict[str, float]` | Return the per-rank-class weight map for the current query. |
| `_config_scent(query: str) -> bool` | Return whether *query* carries config-scent intent. |
| `_ddl_scent(query: str) -> bool` | Return whether *query* carries DDL/schema intent. |
| `_migration_scent(query: str) -> bool` | Return whether *query* carries migration intent. |
| `_vocab_scent(query: str, vocab: tuple[str, ...]) -> bool` | Return whether *query* mentions any word from *vocab* (word or sub-word). |
| `_resource_scent(query: str) -> bool` | Return whether *query* carries config, DDL, or migration scent. |
| `_config_inject_pass(query: str, fused: dict[int, float]) -> dict[int, float]` | Add config chunks into the fused pool for a config-scent query. |
| `_content_weights(config_scent: bool, code_context: bool) -> dict[str, float]` | Return the per-content-type weight map for the current query. |
| `_query_exact_ids(precheck: dict[str, Any]) -> set[int]` | Return chunk ids whose content matches a exact-match term. |
| `_query_quality_gate(query: str, lexical_hit_count: int, informative: list[str], raw_vector_results: list[tuple[int, float]]) -> tuple[bool, list[tuple[int, float]]]` | Evaluate the multi-signal query-quality gate. |
| `_results_saturated(informative: list[str], chunks: list[dict[str, Any]]) -> bool` | Require at least one candidate chunk to match an informative sub-word. |
| `_rescue_eligible(query: str) -> bool` | Return whether the rescue ladder may rescue *query*. |
| `_rescue_symbol_ids() -> set[int] \| None` | Return the definition-chunk ids a symbol-intent query may rescue. |
| `_rescue_envelope(query: str, limit: int, language: str \| None, include_tests: bool, vector_health: bool, content: str = 'all') -> dict[str, Any]` | Run the rescue ladder below an empty ranked path. |
| `_rescue_t1(query: str, limit: int, language: str \| None, include_tests: bool, vector_health: bool, content: str = 'all') -> dict[str, Any] \| None` | Relaxed-lexical rescue: BM25 with a relaxed quality gate. |
| `_rescue_t2(query: str, limit: int, language: str \| None, include_tests: bool, vector_health: bool, content: str = 'all') -> dict[str, Any] \| None` | Literal rescue: case-insensitive substring scan of content/fqn. |
| `_no_match_envelope(vector_health: bool, tiers_tried: list[str], query: str \| None = None, content: str = 'all') -> dict[str, Any]` | Return the honest `no_match` explanation envelope. |
| `_declared_rule_intent(query: str) -> bool` | Return whether *query* asks about declared rules/guards. |
| `_authorization_intent(query: str) -> bool` | Return whether *query* carries permission/validation intent. |
| `_authorization_inject_pass(fused: dict[int, float]) -> dict[int, float]` | Inject authorization-definition chunks into the fused pool. |
| `_is_authorization_chunk(row: Any) -> bool` | Return whether a code_chunks row is an authorization-definition chunk. |
| `_on_topic_scaffold_query(query: str) -> bool` | Return whether *query* is explicitly about a generic construct. |
| `_declared_rules_pass(query: str, fused: dict[int, float]) -> dict[int, float]` | Boost chunks whose declared_rules match a query sub-word. |
| `_code_language_context(explicit_language: str \| None) -> bool` | Return whether a code-language context is active for the query. |
| `_test_file_paths() -> list[str]` | Return the stored paths of all test files in the index. |
| `_fetch_chunks(chunk_ids: list[int]) -> list[dict[str, Any]]` | Fetch `code_chunks` rows for *chunk_ids* as dicts in id order. |
| `_search_exhaustive(query: str, limit: int, language: str \| None, include_tests: bool, vector_health: bool, content: str = 'all', matching: str \| None = None, regex: bool = False) -> dict[str, Any]` | Line-oriented exhaustive scan over the indexed files; *regex* validates the pattern and scans with it. |
| `_search_enumerate(query: str, limit: int, vector_health: bool) -> dict[str, Any]` | Enumerate the named symbol kind ("list all controllers"). |
| `_enumeration_intent(query: str) -> bool` | Whether *query* asks to list all of a kind (enumerate auto-select). |
| `_enumeration_target(query: str) -> str \| None` | Return the enumeration target term of *query*, or `None`. |
| `_enumeration_kinds(target: str) -> list[str] \| None` | Return the `chunk_node_type` filter for a kind word, else `None`. |
| `_resource_patterns(target: str) -> list[str] \| None` | Return `file_path` GLOB patterns for a resource kind word. |
| `_unparseable_files() -> list[str]` | Return indexed files the structural layer could not parse. |
| `_apply_file_coherence(results: list[dict[str, Any]]) -> list[dict[str, Any]]` | Reward files with multiple matching chunks and dedup to one result per file. |
