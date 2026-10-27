# Types

* [ASTParser](ASTParser.md) - Tree-sitter based multi-language AST parser producing chunk boundaries and node trees.
* [AnchorChunk](AnchorChunk.md) - The indexed chunk selected as the anchor for a find-related query.
* [ArchitectureReport](ArchitectureReport.md) - Deterministic architecture overview of the indexed graph (god nodes, communities, import cycles).
* [AuditDatabase](AuditDatabase.md) - Append-only SQLite database for the query audit trail; enforces immutability via SQLite triggers.
* [BM25Search](BM25Search.md) - FTS5-based BM25 keyword search over the indexed code_chunks corpus.
* [BoostVerdict](BoostVerdict.md) - Final bounded boost/no-boost decision produced by the match-boost pass for a single candidate.
* [ConfidenceMatchEvidence](ConfidenceMatchEvidence.md) - Per-result facts used for confidence computation (confidence.py's MatchEvidence, renamed here to avoid collision).
* [ContentIntent](ContentIntent.md) - StrEnum for the content axis a query targets (DOCS, CONFIG, CODE, NEUTRAL).
* [ContentType](ContentType.md) - StrEnum for the content axis an indexed chunk belongs to (code, config, docs).
* [ContextManager](ContextManager.md) - Manages the on-disk context directory holding all persistent index data.
* [DaemonClient](DaemonClient.md) - Client for connecting to and querying a running QueryDaemon over its local socket.
* [DocLinkStore](DocLinkStore.md) - CRUD for offline links between documentation/config chunks and code chunks.
* [EdgeStore](EdgeStore.md) - High-level CRUD for call-graph edges and traversal queries.
* [EmbeddingGenerator](EmbeddingGenerator.md) - Wraps the Model2Vec (potion-code-16m-32d) model to generate text embeddings with warm-up tracking.
* [EnclosingContext](EnclosingContext.md) - A chunk's nearest structural context: module identity, ancestor-name chain, content axis.
* [ExpansionTable](ExpansionTable.md) - Two-way, case-insensitive acronym/phrase to expansion-terms table with fuzzy matching.
* [ExplainAnswer](ExplainAnswer.md) - Result of an explain request: a symbol's ego graph, rationale comments, and linked docs.
* [FileRole](FileRole.md) - StrEnum classifying a file's structural role for behavior/definition reranking.
* [FileWatcher](FileWatcher.md) - Polls the filesystem for content changes using SHA256 hashing; debounces callbacks via threading.Timer.
* [FreshnessChecker](FreshnessChecker.md) - Computes a working-tree-vs-index staleness signal via stat baselines and optional rehashing.
* [GitIgnoreMatcher](GitIgnoreMatcher.md) - Matches paths against a repository's .gitignore files using Git's gitwildmatch semantics.
* [GraphAnswer](GraphAnswer.md) - Result of a graph query: seeds, reachable nodes, edges, and outcome.
* [GraphDatabase](GraphDatabase.md) - Thread-safe SQLite database connection manager for the code graph schema (schema v16).
* [GraphEdge](GraphEdge.md) - Frozen dataclass for a directed, confidence-labelled relation between two graph-answer nodes.
* [GraphNode](GraphNode.md) - Frozen dataclass for a symbol, file, or unresolved external node in a graph answer.
* [GraphQueryService](GraphQueryService.md) - Offline query, path, explain, impact, and architecture reporting over the symbol and module graph.
* [HybridSearch](HybridSearch.md) - Combines BM25 keyword search and vector semantic search via RRF fusion, with quality gates and rescue tiers.
* [ImpactAnswer](ImpactAnswer.md) - Symbols and files impacted by a set of changed files.
* [IndexChangeDetector](IndexChangeDetector.md) - Tracks index metadata (version, mtime, status) and decides reload vs. envelope response on detecting mtime changes.
* [IndexLock](IndexLock.md) - Cross-process file lock preventing concurrent index writes.
* [IndexMetadata](IndexMetadata.md) - Metadata tracking for index change detection (version, mtime, timestamp, status).
* [IndexMetadataStore](IndexMetadataStore.md) - Key-value store for index metadata (status, version, counts, etc.).
* [IndexOrchestrator](IndexOrchestrator.md) - Coordinates full and incremental indexing: parsing, symbol/edge extraction, embedding, and FTS population.
* [IndexStatus](IndexStatus.md) - Enum for index health status (CURRENT, STALE, UNAVAILABLE).
* [LanguageConfig](LanguageConfig.md) - Operator-supplied overrides of the built-in language definitions (extensions and grammar modules).
* [MCPServer](MCPServer.md) - FastMCP server exposing search, code-navigation, and graph-query tools over stdio.
* [MatchEvidence](MatchEvidence.md) - Per-result name-matching evidence used by the match-boost pass (match_boost.py variant).
* [MatchTier](MatchTier.md) - IntEnum ranking the strongest filename/symbol evidence connecting a query to a chunk.
* [MetricsCollector](MetricsCollector.md) - Sliding-window metrics collector computing latency percentiles and tracking redaction counts.
* [ModelState](ModelState.md) - StrEnum for the current embedding model state (WARM, COLD, INITIALIZING).
* [ModuleEdgeStore](ModuleEdgeStore.md) - CRUD and reverse/forward traversal for file-level module_edges rows.
* [PathAnswer](PathAnswer.md) - Result of a shortest-path request between two symbols.
* [PathClass](PathClass.md) - StrEnum giving a file path's rank-relevant structural classification.
* [QueryAnalysis](QueryAnalysis.md) - The query-time trust-signal entity produced by analyze_query and consumed by the search/rerank pipeline.
* [QueryDaemon](QueryDaemon.md) - Background daemon keeping the index warm in memory and serving queries over a local socket.
* [QueryMatchContext](QueryMatchContext.md) - Query-level name-resolution facts (identifier, qualified name, ambiguity, resolution outcome) computed once per request for confidence scoring.
* [QueryNameContext](QueryNameContext.md) - Query-level facts about named-symbol tokens extracted from the query, computed once per request.
* [RationaleStore](RationaleStore.md) - CRUD and full-text search for rationale comments linked to symbols.
* [Redactor](Redactor.md) - Regex-based secret redactor that applies patterns to text and tracks redaction counts.
* [RelevanceScore](RelevanceScore.md) - Final combined relevance score from structural semantic signals and vector similarity.
* [Reranker](Reranker.md) - Adjusts raw search scores using definition/identifier/config-key boosts, canonicality tiers, corpus-hygiene penalties, and session weighting.
* [ResolutionResult](ResolutionResult.md) - Outcome of resolving a name query to a symbol: exact match, ambiguous candidates, or not found.
* [SemanticSignals](SemanticSignals.md) - Structural semantic signals (package overlap, type sharing, call proximity) between an anchor and a candidate symbol.
* [SessionDatabase](SessionDatabase.md) - Tracks code navigation events to enable session-based personalised reranking with exponential decay.
* [Settings](Settings.md) - Central configuration dataclass with 168 CODE_SEARCH_* environment-variable-backed fields and runtime-profile presets.
* [SymbolExtractor](SymbolExtractor.md) - Extracts symbols and edges (calls, imports, inheritance) from tree-sitter ASTs.
* [SymbolReference](SymbolReference.md) - A caller-supplied name parsed into its matching components (raw, leaf, qualifier, signature, form).
* [SymbolStore](SymbolStore.md) - SQLite-backed CRUD, resolution, and lookup for symbol records.
* [VectorIndex](VectorIndex.md) - In-memory/on-disk vector index for cosine-similarity nearest-neighbor search over chunk embeddings.
* [VectorSearch](VectorSearch.md) - Semantic search using the vector index.
* [WarmupState](WarmupState.md) - Lifecycle state of the in-process embedding model (cold, warming, warm, failed, disabled).
