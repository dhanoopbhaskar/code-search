---
type: Index
title: "Engine Modules"
description: "Index of engine package module concepts (the core indexing, search, and ranking engine)."
tags: [modules, engine, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
---

# Engine Modules

* [__init__](__init__.md) - package marker module.
* [audit](audit.md) - immutable query audit trail (`AuditDatabase`).
* [classification](classification.md) - content-type / rank-class classification helpers.
* [confidence](confidence.md) - calibrated confidence scoring and bands.
* [config](config.md) - `Settings` dataclass reading all `CODE_SEARCH_*` environment variables, and `LanguageConfig` loader.
* [daemon](daemon.md) - background `QueryDaemon` and `DaemonClient` for warm-index serving over a Unix socket.
* [embed_representation](embed_representation.md) - builds the enclosing-context + chunk text passed to the embedding model.
* [embeddings](embeddings.md) - `EmbeddingGenerator` and `VectorIndex`/`VectorSearch` (Model2Vec-backed).
* [expansions](expansions.md) - query synonym/expansion table loading.
* [file_role](file_role.md) - structural file-role classification (`FileRole`).
* [freshness](freshness.md) - two-tier stat + rehash freshness detection (`FreshnessChecker`, `IndexChangeDetector`).
* [graph](graph.md) - SQLite-backed call/definition graph (`GraphDatabase`, `SymbolStore`, `EdgeStore`).
* [implementations](implementations.md) - "find implementations" query support.
* [index_metadata](index_metadata.md) - index version/compatibility metadata (`IndexMetadata`, `IndexMetadataStore`, `IndexStatus`).
* [index_service](index_service.md) - `IndexOrchestrator` coordinating full/incremental indexing.
* [indexer](indexer.md) - chunking and index-writing pipeline.
* [intent_detection](intent_detection.md) - query-intent classification (definition/behavior/authorization/DDL/migration/declared-rule).
* [language](language.md) - per-language tree-sitter configuration and vocabularies.
* [match_boost](match_boost.md) - bounded additive match-boost layer (`BoostVerdict`, `MatchEvidence`).
* [metrics](metrics.md) - rolling-window latency metrics collection (`MetricsCollector`).
* [model_status](model_status.md) - embedding model availability/compatibility checks (`ModelState`, `WarmupState`).
* [occurrence_count](occurrence_count.md) - exhaustive/enumerate mode line-occurrence counting.
* [parser](parser.md) - tree-sitter-based AST parsing (`ASTParser`).
* [paths](paths.md) - path normalization and classification (`PathClass`).
* [redactor](redactor.md) - secret redaction and air-gap network enforcement (`Redactor`).
* [reranking](reranking.md) - post-fusion result reranking (`Reranker`).
* [rescue_floor](rescue_floor.md) - rescue-ladder eligibility evaluation.
* [response_service](response_service.md) - builds the final search response envelope.
* [scent_detection](scent_detection.md) - config/DDL "scent" detection in queries and content.
* [search](search.md) - `HybridSearch`, the central BM25 + vector fusion + quality-gate + rescue-ladder orchestrator.
* [semantic_signals](semantic_signals.md) - pure semantic scoring signal functions.
* [session](session.md) - session-based read/write weighting (`SessionDatabase`, `ContextManager`).
* [symbol_resolution](symbol_resolution.md) - symbol reference parsing and resolution (`SymbolReference`, `ResolutionResult`).
* [symbols](symbols.md) - symbol/edge extraction from parsed ASTs (`SymbolExtractor`).
* [watcher](watcher.md) - continuous polling file watcher (`FileWatcher`).
