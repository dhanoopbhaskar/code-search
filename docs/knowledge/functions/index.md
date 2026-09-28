---
type: Index
title: "Functions"
description: "Index of all public top-level function concepts extracted from src/, grouped by module."
tags: [functions, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
---

# Functions by Module

## cli/main.py

* [main](main.md) - CLI entry point; parses args and dispatches subcommands.
* [cmd_index](cmd_index.md) - `index` subcommand handler.
* [cmd_search](cmd_search.md) - `search` subcommand handler.
* [cmd_symbol](cmd_symbol.md) - `symbol` subcommand handler.
* [cmd_graph](cmd_graph.md) - `graph` subcommand handler.
* [cmd_implementations](cmd_implementations.md) - `implementations` subcommand handler.
* [cmd_metrics](cmd_metrics.md) - `metrics` subcommand handler.
* [cmd_daemon](cmd_daemon.md) - `daemon` subcommand handler.
* [cmd_daemon_run](cmd_daemon_run.md) - runs the daemon subcommand's foreground/background logic.
* [cmd_serve](cmd_serve.md) - `serve` subcommand starting the MCP server.
* [cmd_download_models](cmd_download_models.md) - `download-models` subcommand handler.
* [cmd_list_languages](cmd_list_languages.md) - `list-languages` subcommand handler.

## engine/classification.py

* [classify_query](classify_query.md) - classifies a query's shape/mode.
* [classify_content_intent](classify_content_intent.md) - classifies query content-intent (code/config/docs).
* [chunk_rank_class](chunk_rank_class.md) - assigns a rank-class label to a chunk.
* [demote_test_file_candidates](demote_test_file_candidates.md) - demotes test-file matches for non-test queries.

## engine/confidence.py

* [calibrated_confidence](calibrated_confidence.md) - computes a calibrated confidence score.
* [confidence_band](confidence_band.md) - maps a score to a high/medium/low confidence band.
* [confidence_score](confidence_score.md) - core confidence-score computation.
* [is_borderline](is_borderline.md) - detects borderline-confidence results.
* [envelope_band](envelope_band.md) - determines the response envelope's confidence band.

## engine/config.py

* [load_language_config](load_language_config.md) - loads per-language parsing config from disk.

## engine/daemon.py

* [default_socket_path](default_socket_path.md) - resolves the default daemon Unix-socket path.
* [write_pidfile](write_pidfile.md) - writes the daemon's pidfile.
* [clear_pidfile](clear_pidfile.md) - removes the daemon's pidfile.
* [daemon_status](daemon_status.md) - checks whether the daemon is running.
* [run_daemon_foreground](run_daemon_foreground.md) - runs the daemon loop in the foreground.
* [create_server](create_server.md) - constructs the daemon's socket server.

## engine/embed_representation.py

* [build_embed_text](build_embed_text.md) - builds the enclosing-context + chunk text passed to the embedding model.
* [derive_enclosing_context](derive_enclosing_context.md) - derives the enclosing declaration context for a chunk.
* [get_representation_scheme_version](get_representation_scheme_version.md) - returns the current embedding representation scheme version.
* [set_representation_scheme_version](set_representation_scheme_version.md) - sets the embedding representation scheme version (test/tooling use).

## engine/embeddings.py

* [check_index_model_compatibility](check_index_model_compatibility.md) - checks whether an index matches the configured embedding model.
* [check_index_representation_compatibility](check_index_representation_compatibility.md) - checks whether an index matches the current representation scheme.

## engine/file_role.py

* [classify_file_role](classify_file_role.md) - classifies a file's structural role.
* [file_role](file_role.md) - resolves a file's role for a given path.

## engine/graph.py

* [build_symbol_fqn](build_symbol_fqn.md) - builds a symbol's fully-qualified name.
* [find_implementations](find_implementations.md) - finds implementations of an interface/abstract symbol.

## engine/implementations.py

(no additional top-level functions beyond those listed under engine/graph.py and engine/search.py)

## engine/index_service.py

* [index_mtime](index_mtime.md) - resolves the index's last-modified timestamp.
* [normalize_indexed_path](normalize_indexed_path.md) - normalizes a path for consistent index storage/lookup.
* [resolve_stored_path](resolve_stored_path.md) - resolves a stored index path back to an absolute path.

## engine/intent_detection.py

* [detect_definition_intent](detect_definition_intent.md) - detects "where is X defined" query intent.
* [decompose_query](decompose_query.md) - decomposes a query into constituent terms/signals.
* [scope_override](scope_override.md) - determines a scope override from query intent.
* [build_scope_signal](build_scope_signal.md) - builds the scope signal used in query-intent scope inference.

## engine/language.py

* [infer_query_language](infer_query_language.md) - infers the target programming language of a query.
* [language_vocabularies](language_vocabularies.md) - returns per-language vocabulary tables.
* [tokenize](tokenize.md) - tokenizes text using language-aware rules.
* [identify_subwords](identify_subwords.md) - splits identifiers into subwords (camelCase/snake_case).
* [subword_overlap](subword_overlap.md) - computes subword overlap between two identifiers.
* [build_parser](build_parser.md) - builds a tree-sitter parser for a given language.

## engine/match_boost.py

* [compute_verdict](compute_verdict.md) - computes the bounded match-boost verdict for a chunk.
* [is_exact_fqn_match](is_exact_fqn_match.md) - checks for an exact FQN match.
* [is_exact_symbol_match](is_exact_symbol_match.md) - checks for an exact symbol-name match.
* [classify_filename_match](classify_filename_match.md) - classifies the strength of a filename match.
* [classify_path_match](classify_path_match.md) - classifies the strength of a path/stem match.
* [classify_symbol_match](classify_symbol_match.md) - classifies the strength of a symbol match.
* [is_controller_endpoint](is_controller_endpoint.md) - detects controller/endpoint-style symbols.
* [boost_for_tier](boost_for_tier.md) - maps a match tier to its boost value.
* [strongest_tier](strongest_tier.md) - picks the strongest matching tier from multiple candidates.
* [query_symbol_identifier](query_symbol_identifier.md) - extracts a candidate symbol identifier from the query.
* [qualified_query_name](qualified_query_name.md) - builds a qualified name candidate from the query.
* [filename_candidates](filename_candidates.md) - generates candidate filenames implied by the query.
* [normalize_name](normalize_name.md) - normalizes an identifier/name for comparison.
* [exact_precheck](exact_precheck.md) - runs the exact-match pre-check pass.

## engine/model_status.py

* [report_model_status](report_model_status.md) - reports embedding model availability/compatibility.
* [profile_model_available](profile_model_available.md) - checks whether a given model profile's assets are available.

## engine/occurrence_count.py

* [count_occurrences_per_line](count_occurrences_per_line.md) - counts query-term occurrences per matching line.

## engine/paths.py

* [content_type](content_type.md) - classifies a path's `ContentType`.

## engine/redactor.py

* [verify_air_gap](verify_air_gap.md) - verifies outbound network access is blocked.
* [air_gap_enforcement](air_gap_enforcement.md) - context manager/patch enforcing air-gap network blocking.
* [allow_downloads](allow_downloads.md) - narrow escape hatch permitting outbound downloads.

## engine/reranking.py

* [rerank_with_semantic](rerank_with_semantic.md) - reranks fused results using semantic and structural signals.

## engine/rescue_floor.py

* [evaluate_rescue_floor](evaluate_rescue_floor.md) - decides whether rescue-ladder tiers should run.

## engine/response_service.py

* [build_response](build_response.md) - builds the final search response envelope.

## engine/scent_detection.py

* [detect_config_ddl_scent](detect_config_ddl_scent.md) - detects config/DDL "scent" in a query or chunk.

## engine/search.py

* [build_fts_query](build_fts_query.md) - builds the SQLite FTS5 query string.
* [analyze_query](analyze_query.md) - analyzes a query into a `QueryAnalysis` (expansion/language/intent).
* [rrf_fusion](rrf_fusion.md) - Reciprocal Rank Fusion of BM25 and vector result lists.

## engine/semantic_signals.py

* [compute_semantic_score](compute_semantic_score.md) - computes a blended semantic similarity score.
* [compute_call_proximity](compute_call_proximity.md) - computes call-graph proximity between two symbols.
* [compute_package_overlap](compute_package_overlap.md) - computes package/namespace overlap between two files.
* [compute_type_sharing](compute_type_sharing.md) - computes shared-type overlap between two chunks.
* [compute_scent_adjustment](compute_scent_adjustment.md) - computes a scent-based score adjustment.
* [compute_final_score](compute_final_score.md) - combines all semantic signals into a final score.
* [embedded_symbols](embedded_symbols.md) - extracts symbols embedded within a chunk's text.
* [read_source_slice](read_source_slice.md) - reads a slice of source text for a chunk.

## engine/symbol_resolution.py

* [parse_reference](parse_reference.md) - parses a raw callee/reference string into structured parts.
* [resolve_reference](resolve_reference.md) - resolves a parsed reference to an indexed symbol definition.
* [resolve_with_signature](resolve_with_signature.md) - resolves a reference using signature-aware disambiguation.
* [normalize_signature](normalize_signature.md) - normalizes a function/method signature for comparison.
* [strip_params](strip_params.md) - strips parameter lists from a signature string.
* [symbol_leaf](symbol_leaf.md) - extracts the leaf (unqualified) name from a symbol path.
* [outcome_for_kind](outcome_for_kind.md) - maps a resolution outcome to its result kind.
* [is_deprecated](is_deprecated.md) - checks whether a resolved symbol is marked deprecated.

## engine/watcher.py

* [create_watcher](create_watcher.md) - constructs a configured `FileWatcher`.

## mcp/server.py

(MCP tool functions are documented as methods of [`MCPServer`](/types/MCPServer.md) rather than standalone functions.)
