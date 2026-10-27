---
type: Overview
title: "System Overview"
description: "How code-search's indexing, hybrid search, and serving surfaces (CLI, MCP, daemon) fit together."
resource: code_search/
tags: [architecture, overview]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/
    id: source-code
---

# Overview

`code-search` is an AI code context engine for air-gapped,
CPU-only enterprise environments. It provides hybrid (BM25 + vector)
semantic code search, symbol/call-graph navigation, and implementation
discovery over a locally indexed codebase, exposed via a CLI, an MCP
stdio server, and an optional background daemon.

# Major Subsystems

## Indexing Pipeline

[`IndexOrchestrator`](../types/IndexOrchestrator.md) coordinates full and
incremental indexing:

1. File discovery and change detection —
   [`FreshnessChecker`](../types/FreshnessChecker.md) (stat fast-path +
   self-healing rehash) or [`FileWatcher`](../types/FileWatcher.md)
   (continuous polling with debounce). Discovery honours repository
   `.gitignore` files through
   [`GitIgnoreMatcher`](../types/GitIgnoreMatcher.md) unless
   `CODE_SEARCH_RESPECT_GITIGNORE` is `false`.
2. Parsing — [`ASTParser`](../types/ASTParser.md) (tree-sitter, multi-language)
   produces chunk boundaries; the parse workers also extract rationale
   comments (`NOTE`/`WHY`/`HACK`/`TODO`/`FIXME`/`ADR`/`RFC`). Heading-structured
   prose is split by heading and package lockfiles become one bounded infra
   chunk, so neither dominates keyword search.
3. Symbol/edge extraction — [`SymbolExtractor`](../types/SymbolExtractor.md)
   extracts definitions, calls, imports, and inheritance edges, stored via
   [`SymbolStore`](../types/SymbolStore.md) and [`EdgeStore`](../types/EdgeStore.md)
   over [`GraphDatabase`](../types/GraphDatabase.md) (SQLite). FQNs are
   deduplicated per file, and TypeScript/JavaScript imports resolve through
   `tsconfig` aliases and directory barrels. Persistence
   uses one writer connection with files committed in groups of 256; full
   builds suspend the `chunks_fts` triggers and rebuild the keyword index
   once at the end. File-level import edges go to
   [`ModuleEdgeStore`](../types/ModuleEdgeStore.md) and rationale comments to
   [`RationaleStore`](../types/RationaleStore.md).
4. Embedding — [`EmbeddingGenerator`](../types/EmbeddingGenerator.md) (Model2Vec
   `potion-code-16m-32d`) embeds chunk text derived via
   [`build_embed_text`](../functions/build_embed_text.md), stored in
   [`VectorIndex`](../types/VectorIndex.md). With
   `CODE_SEARCH_INDEX_DOC_LINKS` enabled, documentation/config chunks are
   linked to code chunks in [`DocLinkStore`](../types/DocLinkStore.md).
5. Lexical indexing — chunks are also indexed into SQLite FTS5
   (`chunks_fts`) for [`BM25Search`](../types/BM25Search.md).

## Hybrid Search Pipeline

[`HybridSearch`](../types/HybridSearch.md) is the central query-time
orchestrator:

1. Query analysis — [`analyze_query`](../functions/analyze_query.md) builds a
   [`QueryAnalysis`](../types/QueryAnalysis.md) (expansion, language
   inference, definition intent).
2. Scope and intent inference — when no explicit content scope is given,
   [`classify_content_intent`](../functions/classify_content_intent.md) infers
   `code`, `all`, or `code_focused` from the query shape. The CLI, MCP, and
   daemon exclude test files by default, and lexical match counts are split
   into production and test totals.
3. Parallel retrieval — [`BM25Search`](../types/BM25Search.md) and
   [`VectorSearch`](../types/VectorSearch.md) run independently.
4. Quality gate — before fusion, a multi-signal gate (informative-token
   coverage, concept signal, exact-token coverage, and top-vector floors)
   evaluated against the raw BM25 hit count and raw vector results decides
   whether the retrieval evidence is trustworthy enough to proceed. Corpus
   document frequencies come from the persisted `subword_stats` and
   `prefix_stats` tables when present, falling back to a full chunk scan.
5. Fusion — [`rrf_fusion`](../functions/rrf_fusion.md) (Reciprocal Rank Fusion)
   merges both result lists.
6. Rescue ladder — when the ranked path yields nothing, progressively
   looser tiers ([`_rescue_t1`](../modules/engine/search.md) relaxed lexical,
   then `_rescue_t2` literal substring scan) attempt recovery before
   returning `no_match`.
7. Boosting and reranking — [`compute_verdict`](../functions/compute_verdict.md)
   (name-match boost), [`scent`](../functions/compute_scent_adjustment.md)
   adjustments, a concept-symbol pass (definitions whose names carry the
   query's rare terms, using
   [`collapse_terms`](../functions/collapse_terms.md)), an endpoint-intent
   pass (controller methods annotated for the query's HTTP verb), a
   constant-intent pass (constant/config declarations for default-shaped
   queries), and [`Reranker`](../types/Reranker.md) (definition and
   identifier-definition boosts, config-key boost, docs/config canonicality
   tiers, module cohesion, minified/vendor demotion, test-file penalty,
   session weighting, file-role penalties) refine the final order.
8. Abstention — a post-rank gate compares concept coverage and top-vs-median
   score separation; weak evidence yields `no_match` unless `--allow-weak`
   is set.
9. Output — results are treated as ordered evidence: each carries
   `score_normalized`, the envelope reports `token_savings`, and compact
   root-relative JSON (or `--paths-only`) is the default.

## Graph Query Layer

[`GraphQueryService`](../types/GraphQueryService.md) answers multi-hop
questions over the indexed graph without any LLM or network call. It seeds a
bounded, deterministic BFS from the same reranked hits the search surface
returns, records a provenance `reason` on every seed, collapses unresolved
external callee leaves unless asked to include them, walks resolved
`graph_edges` and `module_edges`, and labels every edge `EXTRACTED`,
`INFERRED`, `AMBIGUOUS`, or `UNRESOLVED` from its persisted resolution tier
([`resolve_confidence`](../functions/resolve_confidence.md)).
It provides `query`, `shortest_path`, `explain`, `impact`, and
`architecture_report` operations.

## Serving Surfaces

- **CLI** ([`cli.main`](../modules/cli/main.md)) — direct one-shot
  `index`/`search`/`symbol`/`graph`/`implementations`/`find-related`/`query`/`path`/`explain`/`affected`/`map`/`metrics`/`stats`/`doctor`/`start`/`status`
  commands.
- **MCP server** ([`MCPServer`](../types/MCPServer.md)) — exposes `search`,
  `get_symbol_definition`, `get_call_neighbors`, `get_implementations`,
  `find_related`, `query_graph`, `shortest_path`, `explain_symbol`, and
  `get_impact` as MCP tools over stdio for AI agent consumption.
- **Daemon** ([`QueryDaemon`](../types/QueryDaemon.md)) — keeps the index and
  embedding model warm in memory, served over a local IPC endpoint via
  [`DaemonClient`](../types/DaemonClient.md), avoiding per-invocation
  cold-start cost. A lifecycle-state file reports `starting`/`warming`/
  `ready`.
- **Related-chunk ranking** ([`engine.find_related`](../modules/engine/find_related.md))
  — one implementation shared by the CLI, daemon, and MCP tool.

Index storage has two layouts: the legacy `vectors.bin` + JSON sidecar, and
the compact `vectors.v2.bin` + `CSVMETA1` binary sidecar with an append-only
`.files` dictionary. The `small` runtime profile selects compact storage and
deferred freshness; `standard` keeps legacy storage and blocking freshness.

## Compliance and Observability

[`Redactor`](../types/Redactor.md) and `air_gap_enforcement` (see
[`engine.redactor`](../modules/engine/redactor.md)) enforce secret redaction
and outbound-network blocking for air-gapped deployments.
[`AuditDatabase`](../types/AuditDatabase.md) records an immutable query
trail; [`MetricsCollector`](../types/MetricsCollector.md) tracks latency
percentiles.

# See Also

- [Design Patterns](design-patterns.md)
- [Configuration](../config/environment.md)
