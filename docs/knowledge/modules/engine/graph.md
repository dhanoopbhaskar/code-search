---
type: Module
title: "engine.graph"
description: "SQLite schema and CRUD layer for the code graph: symbols, typed edges, code chunks (FTS5), and index metadata."
resource: src/engine/graph.py
tags: [engine, graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/graph.py
    id: source-code
---

# Overview

SQLite-backed schema and CRUD layer for the code graph: symbols
(function/class/method definitions with FQN, location, docstring), typed
directed edges (`CALLS`, `IMPORTS`, `INHERITS`, `REFERENCES`), code chunks
with FTS5 full-text search, and index metadata (version, status, counts).
Provides thread-safe database access via per-thread connections,
migration logic across 13+ schema versions, and high-level graph
traversal (call graph, inheritance tree, symbol resolution).

# Key Constants

`SCHEMA_VERSION = 13` — current schema target version. `SYMBOLS_TABLE_DDL`,
`GRAPH_EDGES_TABLE_DDL`, `CODE_CHUNKS_TABLE_DDL`, `METADATA_TABLE_DDL`,
`FILE_CHECKSUMS_TABLE_DDL`, `ALL_DDLS` — SQL schema definitions.

# Key Classes

- [`GraphDatabase`](/types/GraphDatabase.md) — thread-safe SQLite connection manager; owns schema creation and migrations.
- [`EdgeStore`](/types/EdgeStore.md) — high-level CRUD for call-graph edges and traversal queries (callers/callees, subtypes, ancestors).
- [`IndexMetadataStore`](/types/IndexMetadataStore.md) — key-value store for index metadata (status, version, counts).

# Key Functions

- [`read_source_slice`](/functions/read_source_slice.md) — read a line-range slice of a source file.

# Internal Helpers

Private helpers implement fuzzy symbol resolution
(`_resolve_symbol_candidates`, `_rank_symbol_candidates`,
`_levenshtein`, `_decompose_leaf`) and candidate summarization
(`_candidate_summary`) used by `EdgeStore.resolve_symbol_definition`.
