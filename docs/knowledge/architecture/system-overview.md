---
type: Overview
title: "System Overview"
description: "How code-search's indexing, hybrid search, and serving surfaces (CLI, MCP, daemon) fit together."
resource: src/
tags: [architecture, overview]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/
    id: source-code
---

# Overview

`code-search` is an in-house AI code context engine for air-gapped,
CPU-only enterprise environments. It provides hybrid (BM25 + vector)
semantic code search, symbol/call-graph navigation, and implementation
discovery over a locally indexed codebase, exposed via a CLI, an MCP
stdio server, and an optional background daemon.

# Major Subsystems

## Indexing Pipeline

[`IndexOrchestrator`](/types/IndexOrchestrator.md) coordinates full and
incremental indexing:

1. File discovery and change detection —
   [`FreshnessChecker`](/types/FreshnessChecker.md) (stat fast-path +
   self-healing rehash) or [`FileWatcher`](/types/FileWatcher.md)
   (continuous polling with debounce).
2. Parsing — [`ASTParser`](/types/ASTParser.md) (tree-sitter, multi-language)
   produces chunk boundaries.
3. Symbol/edge extraction — [`SymbolExtractor`](/types/SymbolExtractor.md)
   extracts definitions, calls, imports, and inheritance edges, stored via
   [`SymbolStore`](/types/SymbolStore.md) and [`EdgeStore`](/types/EdgeStore.md)
   over [`GraphDatabase`](/types/GraphDatabase.md) (SQLite).
4. Embedding — [`EmbeddingGenerator`](/types/EmbeddingGenerator.md) (Model2Vec
   `potion-code-16m-32d`) embeds chunk text derived via
   [`build_embed_text`](/functions/build_embed_text.md), stored in
   [`VectorIndex`](/types/VectorIndex.md).
5. Lexical indexing — chunks are also indexed into SQLite FTS5
   (`chunks_fts`) for [`BM25Search`](/types/BM25Search.md).

## Hybrid Search Pipeline

[`HybridSearch`](/types/HybridSearch.md) is the central query-time
orchestrator:

1. Query analysis — [`analyze_query`](/functions/analyze_query.md) builds a
   [`QueryAnalysis`](/types/QueryAnalysis.md) (expansion, language
   inference, definition intent).
2. Parallel retrieval — [`BM25Search`](/types/BM25Search.md) and
   [`VectorSearch`](/types/VectorSearch.md) run independently.
3. Fusion — [`rrf_fusion`](/functions/rrf_fusion.md) (Reciprocal Rank Fusion)
   merges both result lists.
4. Quality gate — a multi-signal gate decides whether the fused results are
   trustworthy enough to return, informed by
   [`evaluate_rescue_floor`](/functions/evaluate_rescue_floor.md) and
   confidence scoring ([`calibrated_confidence`](/functions/calibrated_confidence.md)).
5. Rescue ladder — when the primary path yields nothing, progressively
   looser tiers (stem rescue, embedded-symbol pass) attempt recovery
   before returning `no_match`.
6. Boosting and reranking — [`compute_verdict`](/functions/compute_verdict.md)
   (name-match boost), [`scent`](/functions/compute_scent_adjustment.md)
   adjustments, and [`Reranker`](/types/Reranker.md) (definition boost,
   test-file penalty, session weighting, file-role penalties) refine the
   final order.

## Serving Surfaces

- **CLI** ([`cli.main`](/modules/cli/main.md)) — direct one-shot
  `index`/`search`/`symbol`/`graph`/`implementations`/`metrics` commands.
- **MCP server** ([`MCPServer`](/types/MCPServer.md)) — exposes `search`,
  `get_symbol_definition`, `get_call_neighbors`, `get_implementations`, and
  `find_related` as MCP tools over stdio for AI agent consumption.
- **Daemon** ([`QueryDaemon`](/types/QueryDaemon.md)) — keeps the index and
  embedding model warm in memory, served over a local Unix socket via
  [`DaemonClient`](/types/DaemonClient.md), avoiding per-invocation
  cold-start cost.

## Compliance and Observability

[`Redactor`](/types/Redactor.md) and `air_gap_enforcement` (see
[`engine.redactor`](/modules/engine/redactor.md)) enforce secret redaction
and outbound-network blocking for air-gapped deployments.
[`AuditDatabase`](/types/AuditDatabase.md) records an immutable query
trail; [`MetricsCollector`](/types/MetricsCollector.md) tracks latency
percentiles.

# See Also

- [Design Patterns](/architecture/design-patterns.md)
- [Configuration](/config/environment.md)
