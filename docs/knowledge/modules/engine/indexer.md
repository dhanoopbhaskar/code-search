---
type: Module
title: "engine.indexer"
description: "Orchestrates full and incremental codebase indexing: discovery, AST parsing, symbol/edge/chunk persistence, embedding generation."
resource: code_search/engine/indexer.py
tags: [engine, indexing, pipeline]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
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
import edges, rationale comments, and (opt-in) documentation links.

# Key Constants

`_PARSE_MIN_BATCH_PER_WORKER` (50) — minimum batch size threshold for
process-pool payoff. `_TYPE_DECLARATION_KINDS` — symbol kinds treated as
type declarations for fallback resolution. `_PERSIST_COMMIT_BATCH` (256) —
files per persistence transaction. `_SQL_VAR_LIMIT` (900) — maximum
placeholders per `IN (...)` query. `_RATIONALE_MARKERS` — the
`NOTE`/`WHY`/`HACK`/`TODO`/`FIXME`/`ADR`/`RFC` comment markers.

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
mentions. `_resolve_chunk_fqn` stamps each
chunk with its enclosing symbol's FQN. `_module_fallback_chunk` and
`_fallback_chunk_file` guarantee at least one chunk per file when AST
parsing yields nothing (resource/unparseable files).
