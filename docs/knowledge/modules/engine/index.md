# Engine Modules

* [__init__](__init__.md) - engine package definition and version constant.
* [audit](audit.md) - immutable query audit trail (`AuditDatabase`).
* [classification](classification.md) - content-type / rank-class classification helpers.
* [confidence](confidence.md) - calibrated confidence scoring and bands.
* [config](config.md) - `Settings` dataclass reading all `CODE_SEARCH_*` environment variables, and `LanguageConfig` loader.
* [daemon](daemon.md) - background `QueryDaemon` and `DaemonClient` for warm-index serving over a Unix socket.
* [embed_representation](embed_representation.md) - builds the enclosing-context + chunk text passed to the embedding model.
* [embeddings](embeddings.md) - `EmbeddingGenerator` and the Model2Vec-backed `VectorIndex`.
* [expansions](expansions.md) - query synonym/expansion table loading.
* [file_role](file_role.md) - file-role classification with evidence-based overrides (`classify_file_role`).
* [find_related](find_related.md) - shared find-related anchor resolution and neighbour ranking (CLI, daemon, MCP).
* [freshness](freshness.md) - two-tier stat + rehash freshness detection (`FreshnessChecker`).
* [graph](graph.md) - SQLite-backed call/definition graph (`GraphDatabase`, `EdgeStore`, `ModuleEdgeStore`, `RationaleStore`, `DocLinkStore`, `IndexMetadataStore`).
* [graph_query](graph_query.md) - bounded graph query/path/explain/impact traversal with provenance labels (`GraphQueryService`).
* [implementations](implementations.md) - "find implementations" query support.
* [index_metadata](index_metadata.md) - index version/health metadata (`IndexMetadata`, `IndexStatus`).
* [index_service](index_service.md) - server-side index-staleness detection (`IndexChangeDetector`).
* [indexer](indexer.md) - full/incremental indexing pipeline (`IndexOrchestrator`, `IndexLock`).
* [intent_detection](intent_detection.md) - lexical content-intent classification (docs/config/code/neutral) and scope-signal messages.
* [language](language.md) - query-time language inference and corpus vocabularies (`QueryAnalysis`).
* [match_boost](match_boost.md) - bounded additive match-boost layer (`BoostVerdict`, `MatchEvidence`).
* [metrics](metrics.md) - rolling-window latency metrics collection (`MetricsCollector`).
* [model_status](model_status.md) - embedding model warm/cold status reporting (`ModelState`).
* [occurrence_count](occurrence_count.md) - exhaustive/enumerate mode line-occurrence counting.
* [parser](parser.md) - tree-sitter-based AST parsing (`ASTParser`).
* [paths](paths.md) - path normalization and stored-path resolution.
* [query_terms](query_terms.md) - rule-based query normalization (morphological variants, concept-term collapsing).
* [redactor](redactor.md) - secret redaction and air-gap network enforcement (`Redactor`).
* [reranking](reranking.md) - post-fusion result reranking (`Reranker`).
* [rescue_floor](rescue_floor.md) - rescue-ladder eligibility evaluation.
* [response_service](response_service.md) - builds the final search response envelope and shapes compact, root-relative output.
* [scent_detection](scent_detection.md) - config/DDL "scent" detection in queries and content.
* [search](search.md) - `HybridSearch`, the central BM25 + vector fusion + quality-gate + rescue-ladder orchestrator.
* [semantic_signals](semantic_signals.md) - semantic scoring signal functions.
* [session](session.md) - session-based read/write weighting (`SessionDatabase`).
* [symbol_resolution](symbol_resolution.md) - symbol reference parsing and resolution (`SymbolReference`, `ResolutionResult`).
* [symbols](symbols.md) - symbol/edge extraction from parsed ASTs and symbol CRUD (`SymbolExtractor`, `SymbolStore`).
* [watcher](watcher.md) - continuous polling file watcher (`FileWatcher`).
