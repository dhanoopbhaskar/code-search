---
type: Class
title: "IndexOrchestrator"
description: "Coordinates full and incremental indexing: parsing, symbol/edge extraction, embedding, and FTS population."
resource: code_search/engine/indexer.py#IndexOrchestrator
tags: [indexer, orchestration, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/indexer.py
    id: source-code
---

# Overview

Coordinates full and incremental indexing: file discovery, tree-sitter
parsing, symbol/edge extraction, chunk embedding, and FTS5 population.
Besides symbols, edges, and chunks it persists file-level import edges
([`ModuleEdgeStore`](ModuleEdgeStore.md)), rationale comments
([`RationaleStore`](RationaleStore.md)), and, when
`CODE_SEARCH_INDEX_DOC_LINKS` is enabled, documentation links
([`DocLinkStore`](DocLinkStore.md)). Prose files are split by heading
(ATX/AsciiDoc/setext, fence-aware) and package lockfiles become a single
infra chunk so they cannot dominate keyword search. TypeScript/JavaScript
imports resolve through `tsconfig` `baseUrl`/`paths` aliases and
directory barrel `index` files. Files larger than `max_file_bytes` are
skipped and counted in `skipped_large_files`; graph persistence is gated by
`index_graph`; and after persistence the orchestrator rebuilds the
`subword_stats`/`prefix_stats` tables and records `corpus_chunk_count` and
`index_layout`. Defined in [`engine.indexer`](../modules/engine/indexer.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, metadata_store: IndexMetadataStore, parser: ASTParser, symbol_extractor: SymbolExtractor, symbol_store: SymbolStore, embedding_generator: EmbeddingGenerator, vector_index: VectorIndex, context_dir: Path, settings: Settings \| None = None, edge_store: EdgeStore \| None = None, freshness: Any \| None = None) -> None` | Initialize the orchestrator with all pipeline dependencies. |
| `index_codebase(root_path: Path, force: bool = False, incremental: bool = False, verbose: bool = False, exclusion_patterns: set[str] \| None = None, include_tests: bool = True, include_resources: bool = False, resource_extensions: tuple[str, ...] \| None = None, progress_callback: ProgressCallback \| None = None, status_callback: StatusCallback \| None = None) -> dict[str, Any]` | Run a full or incremental index over *root_path*; *progress_callback* receives `(phase, completed, total)` for the `parsing`, `persisting`, and `embedding` phases and *status_callback* receives a message per finalization step. |
| `prune_stale_files(root_path: Path, include_tests: bool = True, include_resources: bool = True, resource_extensions: tuple[str, ...] \| None = None, exclusion_patterns: set[str] \| None = None) -> dict[str, Any]` | Prune index rows for files no longer on disk or indexable. |
| `_load_tsconfig_aliases(root_path: Path) -> tuple[Path \| None, list[tuple[str, list[str]]]]` | Read `baseUrl`/`paths` from `tsconfig.json` and `tsconfig.*.json` variants. |
| `_resolve_ts_alias(specifier: str, base_dir: Path \| None, paths: list[tuple[str, list[str]]]) -> Path \| None` | Resolve a bare TS module specifier through the path mappings; external packages yield `None`. |
| `_ts_module_candidates(base: str) -> list[str]` | Expand a TS specifier to the index-relative paths it may resolve to (explicit extensions, `.js`→`.ts`, directory `index` barrels). |
| `_persist_module_edges(root_path: Path, import_edges: list[dict[str, Any]]) -> None` | Resolve import edges to file paths (including TypeScript aliases/barrels) for [`ModuleEdgeStore`](ModuleEdgeStore.md). |
