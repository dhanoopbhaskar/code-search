---
type: Index
title: "Functions"
description: "Index of all public top-level function concepts extracted from code_search/, grouped by module."
tags: [functions, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
---

# Functions by Module

## cli/main.py

* [build_parser](build_parser.md) - Build the full argparse tree with all subcommands.
* [cmd_affected](cmd_affected.md) - Handler for the `affected` subcommand: reports symbols impacted by changed files.
* [cmd_daemon](cmd_daemon.md) - Handler for the `daemon` subcommand: start/stop/status control of the QueryDaemon.
* [cmd_daemon_run](cmd_daemon_run.md) - Handler that runs the daemon blocking in the foreground (used internally by `cmd_daemon start`).
* [cmd_download_models](cmd_download_models.md) - Handler for the `download-models` subcommand: fetches the embedding model into the Hugging Face cache.
* [cmd_explain](cmd_explain.md) - Handler for the `explain` subcommand: prints a symbol's metadata, relations, rationale, and linked docs.
* [cmd_find_related](cmd_find_related.md) - Handler for the `find-related` subcommand: prints chunks semantically related to a file/line anchor.
* [cmd_graph](cmd_graph.md) - Handler for the `graph` subcommand: prints callers/callees of a symbol.
* [cmd_implementations](cmd_implementations.md) - Handler for the `implementations` subcommand: prints subtypes or ancestors of a symbol.
* [cmd_index](cmd_index.md) - Handler for the `index` subcommand: builds or rebuilds the code index.
* [cmd_list_languages](cmd_list_languages.md) - Handler for the `list-languages` subcommand: prints supported languages.
* [cmd_map](cmd_map.md) - Handler for the `map` subcommand: generates a deterministic architecture report.
* [cmd_metrics](cmd_metrics.md) - Handler for the `metrics` subcommand: prints latency percentiles and redaction counts.
* [cmd_path](cmd_path.md) - Handler for the `path` subcommand: prints the shortest graph path between two symbols.
* [cmd_query](cmd_query.md) - Handler for the `query` subcommand: answers a question by bounded graph traversal.
* [cmd_search](cmd_search.md) - Handler for the `search` subcommand: runs a hybrid search query and prints results.
* [cmd_serve](cmd_serve.md) - Handler for the `serve` subcommand: starts the MCP stdio server.
* [cmd_symbol](cmd_symbol.md) - Handler for the `symbol` subcommand: resolves and prints a symbol's definition.
* [main](main.md) - Parse arguments and dispatch to the selected subcommand handler.

## engine/classification.py

* [content_type](content_type.md) - Classify a file into the content axis (code, docs, config).
* [file_role](file_role.md) - Resolve a file's role from path/filename signals alone.

## engine/confidence.py

* [calibrated_confidence](calibrated_confidence.md) - Full calibrated confidence for one candidate, combining base score with exact-match evidence boosts.
* [confidence_band](confidence_band.md) - Map a calibrated confidence score to a discrete band label (high/medium/low).
* [confidence_score](confidence_score.md) - Base lexical/vector blend confidence score for one candidate.
* [envelope_band](envelope_band.md) - Aggregate confidence band for the overall response envelope from a list of per-result bands.
* [is_borderline](is_borderline.md) - Whether a confidence score falls in the borderline zone between bands.
* [is_controller_endpoint](is_controller_endpoint.md) - Whether a symbol looks like a web controller/route endpoint (a high-trust signal for authorization-intent queries).
* [is_exact_fqn_match](is_exact_fqn_match.md) - Whether a candidate's FQN exactly matches the query's qualified name.
* [is_exact_symbol_match](is_exact_symbol_match.md) - Whether a candidate's short symbol name exactly matches a query token.
* [qualified_query_name](qualified_query_name.md) - Extract the qualified name portion of a query, if any.
* [subword_overlap](subword_overlap.md) - Fraction of distinct query concepts present in a candidate's text.

## engine/config.py

* [load_language_config](load_language_config.md) - Load custom language configuration from JSON.

## engine/daemon.py

* [clear_pidfile](clear_pidfile.md) - Remove the daemon's pidfile on clean shutdown.
* [daemon_status](daemon_status.md) - Report {running, warm, socket, pid} for a context directory's daemon.
* [default_socket_path](default_socket_path.md) - The daemon's socket path convention for a context directory.
* [pid_is_alive](pid_is_alive.md) - Whether the daemon pidfile records a live process.
* [run_daemon_foreground](run_daemon_foreground.md) - Run the daemon blocking in the foreground.
* [write_pidfile](write_pidfile.md) - Write the daemon's pidfile for lifecycle tracking.

## engine/embed_representation.py

* [build_embed_text](build_embed_text.md) - Compose bounded embedding input text (context prefix + body).
* [derive_enclosing_context](derive_enclosing_context.md) - Build the enclosing context for a chunk from its per-file symbol list.

## engine/embeddings.py

* [check_index_model_compatibility](check_index_model_compatibility.md) - Raise when the index was built by a different embedding model.
* [check_index_representation_compatibility](check_index_representation_compatibility.md) - Raise when stored embeddings predate the running representation scheme.
* [get_representation_scheme_version](get_representation_scheme_version.md) - Read the stored chunk-representation scheme version from index metadata.
* [profile_model_available](profile_model_available.md) - Whether the active model profile is available locally.
* [set_representation_scheme_version](set_representation_scheme_version.md) - Persist the current chunk-representation scheme version into index metadata.

## engine/file_role.py

* [classify_file_role](classify_file_role.md) - Classify a file's role for ranking adjustment, with evidence-based overrides.

## engine/graph.py

* [read_source_slice](read_source_slice.md) - Read a line-range slice of a source file.

## engine/graph_query.py

* [compact_json](compact_json.md) - Serialise a payload to JSON without indentation for compact agent transport.
* [display_symbol](display_symbol.md) - Strip an FQN's filesystem path prefix for human display.
* [edge_resolution_stats](edge_resolution_stats.md) - Per-edge-type resolved/unresolved counts used as a graph-quality metric.
* [render_architecture_markdown](render_architecture_markdown.md) - Render an ArchitectureReport as deterministic Markdown.
* [render_explain_text](render_explain_text.md) - Render an ExplainAnswer with metadata, relations, rationale, and linked docs.
* [render_impact_text](render_impact_text.md) - Render an ImpactAnswer as text with production and test buckets.
* [render_path_text](render_path_text.md) - Render a PathAnswer as a hop-by-hop chain.
* [render_query_text](render_query_text.md) - Render a GraphAnswer as compact, agent-friendly text.
* [relative_display](relative_display.md) - Render a stored file path relative to the index root in POSIX form.
* [resolve_confidence](resolve_confidence.md) - Map a persisted edge resolution tier to an EXTRACTED/INFERRED/AMBIGUOUS/UNRESOLVED label.
* [symbol_source_slice](symbol_source_slice.md) - Return the source text spanned by a symbol row.

## engine/implementations.py

* [find_implementations](find_implementations.md) - Resolve static implementations of an interface member or type.

## engine/index_service.py

* [index_mtime](index_mtime.md) - Extract the index's last build time from the metadata store.

## engine/intent_detection.py

* [build_scope_signal](build_scope_signal.md) - Generate a surface-neutral scope message explaining an exclusion.
* [classify_content_intent](classify_content_intent.md) - Classify a query lexically into docs/config/code/neutral.
* [scope_override](scope_override.md) - The neutral scope token that would include the intent's content type.

## engine/language.py

* [analyze_query](analyze_query.md) - Build the QueryAnalysis entity for a query (the one shared rule).
* [detect_definition_intent](detect_definition_intent.md) - Detect definition phrasing and resolve its target.
* [embedded_symbols](embedded_symbols.md) - Resolved symbol short names embedded in a natural-language query.
* [infer_query_language](infer_query_language.md) - Infer a query's language.
* [language_vocabularies](language_vocabularies.md) - Map each indexed language to its exact sub-word set.

## engine/match_boost.py

* [boost_for_tier](boost_for_tier.md) - Bounded additive boost for a match tier.
* [classify_filename_match](classify_filename_match.md) - Per-signal classifier detecting filename-level match strength.
* [classify_path_match](classify_path_match.md) - Per-signal classifier detecting path-segment match strength.
* [classify_symbol_match](classify_symbol_match.md) - Per-signal classifier detecting symbol-name match strength.
* [compute_verdict](compute_verdict.md) - Bounded boost verdict for one candidate.
* [filename_candidates](filename_candidates.md) - Chunk ids whose file name/stem equals the query.
* [normalize_name](normalize_name.md) - Casefold and strip separators for comparison.
* [strongest_tier](strongest_tier.md) - Highest-priority tier in an iterable.

## engine/model_status.py

* [report_model_status](report_model_status.md) - Generate the model warm/cold status report with latency breakdown.

## engine/occurrence_count.py

* [count_occurrences_per_line](count_occurrences_per_line.md) - Count occurrences of a pattern per line in text.

## engine/paths.py

* [normalize_indexed_path](normalize_indexed_path.md) - Resolve a path against the indexed repo root, collapsing symlinks and ../ segments.
* [resolve_stored_path](resolve_stored_path.md) - Return the stored code_chunks.file_path spelling for a candidate path.

## engine/query_terms.py

* [collapse_terms](collapse_terms.md) - Collapse prefix-related query terms into one representative per concept.
* [concept_terms](concept_terms.md) - Return collapsed concept terms of at least a minimum length.
* [morphological_variants](morphological_variants.md) - Return a word plus conservative English base forms (plural, gerund, past tense).

## engine/redactor.py

* [air_gap_enforcement](air_gap_enforcement.md) - Context manager blocking all outbound socket connections.
* [allow_downloads](allow_downloads.md) - Context manager temporarily allowing outbound socket connections.
* [verify_air_gap](verify_air_gap.md) - Verify that air-gap enforcement is active.

## engine/reranking.py

* [demote_test_file_candidates](demote_test_file_candidates.md) - Demote test-file chunks inside the candidate pool before fusion.

## engine/rescue_floor.py

* [evaluate_rescue_floor](evaluate_rescue_floor.md) - Evaluate whether the rescue tier should return results.

## engine/response_service.py

* [build_response](build_response.md) - Build a search response, checking for the index-change envelope and code-scoped config hints.
* [compact_result](compact_result.md) - Return a trimmed, agent-sized version of a search result.
* [compact_results](compact_results.md) - Apply compact_result to every result in a list.
* [relativize_results](relativize_results.md) - Return results with file_path/fqn relative to the index root.

## engine/scent_detection.py

* [compute_scent_adjustment](compute_scent_adjustment.md) - Multiplicative ranking adjustment for a file under config/DDL scent.
* [detect_config_ddl_scent](detect_config_ddl_scent.md) - Detect config/DDL scent signals in a query string.

## engine/search.py

* [build_fts_query](build_fts_query.md) - Build an FTS5 MATCH expression from decomposed sub-words.
* [chunk_rank_class](chunk_rank_class.md) - Classify a chunk as code/boilerplate/resource.
* [classify_query](classify_query.md) - Classify a query as symbol-like or natural-language.
* [decompose_query](decompose_query.md) - Tokenize and decompose a full query into its sub-word set.
* [exact_precheck](exact_precheck.md) - Detect concrete literal/annotation/identifier patterns in a query.
* [identify_subwords](identify_subwords.md) - Split identifier-style tokens into their constituent sub-words (camelCase/snake_case decomposition).
* [query_symbol_identifier](query_symbol_identifier.md) - Extract a candidate symbol identifier from a query, if it looks like one.
* [rrf_fusion](rrf_fusion.md) - Reciprocal Rank Fusion of BM25 and vector result lists.
* [tokenize](tokenize.md) - Tokenization and identifier decomposition of raw text.

## engine/semantic_signals.py

* [compute_call_proximity](compute_call_proximity.md) - Inverse call-graph depth between two symbols.
* [compute_final_score](compute_final_score.md) - Fuse semantic signals with vector similarity.
* [compute_package_overlap](compute_package_overlap.md) - Jaccard similarity of namespace directory segments.
* [compute_semantic_score](compute_semantic_score.md) - Compute all three semantic signals for a candidate.
* [compute_type_sharing](compute_type_sharing.md) - Normalized signature comparison score.
* [rerank_with_semantic](rerank_with_semantic.md) - Rerank vector results using semantic signals.

## engine/symbol_resolution.py

* [is_deprecated](is_deprecated.md) - Whether declared_rules carries a deprecation marker.
* [normalize_signature](normalize_signature.md) - Parse and normalize a (params) signature.
* [outcome_for_kind](outcome_for_kind.md) - Map an envelope kind to a user-visible outcome.
* [parse_reference](parse_reference.md) - Parse a query into a SymbolReference.
* [resolve_reference](resolve_reference.md) - Apply resolution tiers to rank candidates.
* [resolve_with_signature](resolve_with_signature.md) - Signature-aware overload disambiguation.
* [strip_params](strip_params.md) - Remove the parameter-list suffix from a symbol name-shape string.
* [symbol_leaf](symbol_leaf.md) - Return the trailing (leaf) segment of a dotted or qualified symbol name.

## engine/symbols.py

* [build_symbol_fqn](build_symbol_fqn.md) - Construct a symbol's fully-qualified name.

## engine/watcher.py

* [create_watcher](create_watcher.md) - Convenience factory returning a fully-configured FileWatcher.

## mcp/server.py

* [create_server](create_server.md) - Create an MCPServer around a component registry.

The MCP tools (`search`, `get_symbol_definition`, `get_call_neighbors`, `get_implementations`, `find_related`) are nested inside `MCPServer.build_fastmcp`; see [`MCPServer`](../types/MCPServer.md).
