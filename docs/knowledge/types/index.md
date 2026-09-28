---
type: Index
title: "Types"
description: "Index of all class/dataclass/enum concepts extracted from src/."
tags: [types, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
---

# Types

* [ASTParser](ASTParser.md) - tree-sitter-based multi-language AST parser.
* [AuditDatabase](AuditDatabase.md) - immutable query audit trail (SQLite).
* [BM25Search](BM25Search.md) - SQLite FTS5 BM25 lexical search.
* [BoostVerdict](BoostVerdict.md) - bounded match-boost decision (match_boost.py).
* [ConfidenceMatchEvidence](ConfidenceMatchEvidence.md) - raw evidence for confidence scoring (confidence.py; see naming note re: `MatchEvidence`).
* [ContentIntent](ContentIntent.md) - query content-intent classification enum.
* [ContentType](ContentType.md) - indexed-chunk content-type axis enum (code/config/docs).
* [ContextManager](ContextManager.md) - session/context orchestration.
* [DaemonClient](DaemonClient.md) - Unix-socket client for the background query daemon.
* [EdgeStore](EdgeStore.md) - call/inheritance edge persistence.
* [EmbeddingGenerator](EmbeddingGenerator.md) - Model2Vec-backed chunk embedding generator.
* [EnclosingContext](EnclosingContext.md) - enclosing declaration/context for a chunk.
* [ExpansionTable](ExpansionTable.md) - query synonym/expansion lookup table.
* [FileRole](FileRole.md) - structural file-role classification enum.
* [FileWatcher](FileWatcher.md) - continuous polling file-change watcher.
* [FreshnessChecker](FreshnessChecker.md) - two-tier stat + rehash freshness detector.
* [GraphDatabase](GraphDatabase.md) - SQLite-backed call/definition graph store.
* [HybridSearch](HybridSearch.md) - central BM25 + vector fusion search orchestrator.
* [IndexChangeDetector](IndexChangeDetector.md) - detects changed files since last index.
* [IndexLock](IndexLock.md) - filesystem lock guarding concurrent index writes.
* [IndexMetadata](IndexMetadata.md) - index version/compatibility metadata record.
* [IndexMetadataStore](IndexMetadataStore.md) - persistence for `IndexMetadata`.
* [IndexOrchestrator](IndexOrchestrator.md) - coordinates full/incremental indexing pipeline.
* [IndexStatus](IndexStatus.md) - index freshness/compatibility status enum.
* [LanguageConfig](LanguageConfig.md) - per-language tree-sitter parsing configuration.
* [MCPServer](MCPServer.md) - FastMCP stdio server wrapper.
* [MatchEvidence](MatchEvidence.md) - raw evidence for match-boost decisions (match_boost.py).
* [MatchTier](MatchTier.md) - match-strength tier enum.
* [MetricsCollector](MetricsCollector.md) - rolling-window latency metrics collector.
* [ModelState](ModelState.md) - embedding model availability state enum.
* [PathClass](PathClass.md) - normalized path category enum.
* [QueryAnalysis](QueryAnalysis.md) - result of `analyze_query` (expansion, language, intent).
* [QueryDaemon](QueryDaemon.md) - background warm-index query server.
* [QueryMatchContext](QueryMatchContext.md) - match-boost query-side context.
* [QueryNameContext](QueryNameContext.md) - parsed name-matching context for a query.
* [Redactor](Redactor.md) - secret redaction engine.
* [RelevanceScore](RelevanceScore.md) - fused relevance score breakdown.
* [Reranker](Reranker.md) - post-fusion result reranker.
* [ResolutionResult](ResolutionResult.md) - outcome of resolving a symbol reference.
* [SemanticSignals](SemanticSignals.md) - bundle of pure semantic scoring signals.
* [SessionDatabase](SessionDatabase.md) - session read/write history store.
* [Settings](Settings.md) - the `CODE_SEARCH_*`-backed configuration dataclass.
* [SymbolExtractor](SymbolExtractor.md) - extracts symbol definitions from a parsed AST.
* [SymbolReference](SymbolReference.md) - parsed reference to a symbol (call/import/inheritance).
* [SymbolStore](SymbolStore.md) - symbol definition persistence.
* [VectorIndex](VectorIndex.md) - embedding vector storage/similarity search.
* [VectorSearch](VectorSearch.md) - vector-similarity search over `VectorIndex`.
* [WarmupState](WarmupState.md) - daemon/model warm-up progress state.
