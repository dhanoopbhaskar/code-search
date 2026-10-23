---
type: Module
title: "engine.indexer"
description: "Orchestrates full and incremental codebase indexing: discovery, AST parsing, symbol/edge/chunk persistence, corpus statistics, and embedding generation."
resource: code_search/engine/indexer.py
tags: [engine, indexing, pipeline]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/indexer.py
    id: source-code
---

# Overview

Orchestrates full and incremental codebase indexing by coordinating file
discovery, AST parsing, symbol and edge extraction, code chunking,
embedding generation, and persistence to the graph database and vector
index. The pipeline runs in four phases: (1) serial file discovery with
content-hash diffing, (2) parallel AST parsing via a process pool, (3)
serial symbol/edge/chunk persistence with cross-file edge resolution, and
(4) serial, in-process embedding generation. Persistence runs on one writer
connection with files committed in groups (`_PERSIST_COMMIT_BATCH` = 256);
full builds suspend the `chunks_fts` triggers via
[`GraphDatabase.set_fts_triggers`](../../types/GraphDatabase.md) and rebuild
the keyword index once afterwards. The pipeline also persists file-level
import edges, rationale comments, and (opt-in) documentation links. Prose
files are split by heading (ATX/AsciiDoc/setext, fence-aware) and package
lockfiles are stored as a single bounded infra chunk so a lockfile cannot
dominate keyword search. TypeScript/JavaScript imports resolve through
`tsconfig` `baseUrl`/`paths` aliases and directory barrel `index` files.

Files larger than `max_file_bytes` (default 1 MB) are skipped before
parsing and counted in `skipped_large_files`; the skip is visible in index
metadata because exhaustive search only sees indexed files. Graph
persistence (call/import edges, rationale, doc links) is gated by
`index_graph`, and the run records `graph_indexed`. Once persistence
finishes, the orchestrator rebuilds the `subword_stats`/`prefix_stats`
document-frequency tables, records `corpus_chunk_count` and `index_layout`,
then asks the graph database to compact storage.

# Key Constants

`_PARSE_MIN_BATCH_PER_WORKER` (50) — minimum batch size threshold for
process-pool payoff. `_TYPE_DECLARATION_KINDS` — symbol kinds treated as
type declarations for fallback resolution. `_PERSIST_COMMIT_BATCH` (256) —
files per persistence transaction. `_SQL_VAR_LIMIT` (900) — maximum
placeholders per `IN (...)` query. `_RATIONALE_MARKERS` — the
`NOTE`/`WHY`/`HACK`/`TODO`/`FIXME`/`ADR`/`RFC` comment markers.
`_LOCKFILE_CHUNK_CHARS` (2000) bounds a lockfile's single chunk;
`_HEADING_PROSE_EXTENSIONS`/`_ATX_HEADING`/`_ADOC_HEADING`/`_FENCE_OPEN`/
`_SETEXT_UNDERLINE` define heading-based prose splitting.

# Key Classes

- [`IndexLock`](../../types/IndexLock.md) — filesystem-based exclusive lock (`O_CREAT|O_EXCL`) with stale-lock detection.
- [`IndexOrchestrator`](../../types/IndexOrchestrator.md) — top-level coordinator for the four-phase indexing pipeline.

# Internal Helpers

`_process_file_worker` is the pickle-safe worker function run in the
process pool for parallel AST parsing; it also calls `_extract_rationale`,
which attaches comment lines containing a rationale marker to the nearest
enclosing symbol (`ADR`/`RFC` map to the `adr` kind). `_chunked` splits id
lists to stay under `_SQL_VAR_LIMIT`. On the orchestrator,
`_persist_module_edges` resolves imports to file paths (Java through the
symbol catalog's conventional FQN, Python through a module-name index) and
keeps unresolved imports with `resolved = 0`, and `_persist_doc_links` links
doc/config chunks to code chunks by embedding similarity and exact symbol
mentions. `_prose_heading_chunks` splits heading-structured prose when the
AST yields nothing, and `_lockfile_chunk` produces the single bounded
lockfile record with FQN `<file>::lockfile`. `_load_tsconfig_aliases`,
`_resolve_ts_alias`, and `_ts_module_candidates` resolve TypeScript import
specifiers (including `.js`→`.ts` and directory barrels).
`_resolve_chunk_fqn` stamps each chunk with its enclosing symbol's FQN.
`_module_fallback_chunk` and `_fallback_chunk_file` guarantee at least one
chunk per file when AST parsing yields nothing (resource/unparseable
files). `_rebuild_corpus_stats` counts each token and 3-character prefix
once per `(language, chunk)` pair and persists the rows the query path
reads; every chunk row also carries an `is_test` flag derived from
`_is_test_file`.
