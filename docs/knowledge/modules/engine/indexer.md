---
type: Module
title: "engine.indexer"
description: "Orchestrates full and incremental codebase indexing: discovery, AST parsing, symbol/edge/chunk persistence, embedding generation."
resource: src/engine/indexer.py
tags: [engine, indexing, pipeline]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/indexer.py
    id: source-code
---

# Overview

Orchestrates full and incremental codebase indexing by coordinating file
discovery, AST parsing, symbol and edge extraction, code chunking,
embedding generation, and persistence to the graph database and vector
index. The pipeline runs in four phases: (1) serial file discovery with
content-hash diffing, (2) parallel AST parsing via a process pool, (3)
serial symbol/edge/chunk persistence with cross-file edge resolution, and
(4) parallel embedding generation.

# Key Constants

`_PARSE_MIN_BATCH_PER_WORKER` (50) — minimum batch size threshold for
process-pool payoff. `_TYPE_DECLARATION_KINDS` — symbol kinds treated as
type declarations for fallback resolution.

# Key Classes

- [`IndexLock`](/types/IndexLock.md) — filesystem-based exclusive lock (`O_CREAT|O_EXCL`) with stale-lock detection.
- [`IndexOrchestrator`](/types/IndexOrchestrator.md) — top-level coordinator for the four-phase indexing pipeline.

# Internal Helpers

`_process_file_worker` is the pickle-safe worker function run in the
process pool for parallel AST parsing. `_resolve_chunk_fqn` stamps each
chunk with its enclosing symbol's FQN. `_module_fallback_chunk` and
`_fallback_chunk_file` guarantee at least one chunk per file when AST
parsing yields nothing (resource/unparseable files).
