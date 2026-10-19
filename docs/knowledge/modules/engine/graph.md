---
type: Module
title: "engine.graph"
description: "SQLite schema and CRUD layer for the code graph: symbols, typed edges, code chunks (FTS5), and index metadata."
resource: code_search/engine/graph.py
tags: [engine, graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

SQLite-backed schema and CRUD layer for the code graph: symbols
(function/class/method definitions with FQN, location, docstring), typed
directed edges (`CALLS`, `IMPORTS`, `INHERITS`, `REFERENCES`), code chunks
with FTS5 full-text search, file-level `module_edges`, rationale comments
(`symbol_rationale` with `rationale_fts`), offline `doc_links`, and index
metadata (version, status, counts).
Provides thread-safe database access via per-thread connections,
forward-migration logic for older schema versions, and high-level graph
traversal (call graph, inheritance tree, symbol resolution).

# Key Constants

`SCHEMA_VERSION = 14` — current schema target version. `SYMBOLS_TABLE_DDL`,
`GRAPH_EDGES_TABLE_DDL`, `CODE_CHUNKS_TABLE_DDL`, `METADATA_TABLE_DDL`,
`FILE_CHECKSUMS_TABLE_DDL`, `MODULE_EDGES_TABLE_DDL`,
`SYMBOL_RATIONALE_TABLE_DDL`, `RATIONALE_FTS_DDL`, `DOC_LINKS_TABLE_DDL`,
`ALL_DDLS` — SQL schema definitions. `CHUNKS_FTS_TRIGGER_NAMES` names the
three `chunks_fts` triggers that full builds suspend.

# Key Classes

- [`GraphDatabase`](../../types/GraphDatabase.md) — thread-safe SQLite connection manager; owns schema creation and migrations.
- [`EdgeStore`](../../types/EdgeStore.md) — high-level CRUD for call-graph edges and traversal queries (callers/callees, subtypes, ancestors).
- [`IndexMetadataStore`](../../types/IndexMetadataStore.md) — key-value store for index metadata (status, version, counts).
- [`ModuleEdgeStore`](../../types/ModuleEdgeStore.md) — file-level import edges and their traversal.
- [`RationaleStore`](../../types/RationaleStore.md) — rationale comments linked to symbols, with full-text search.
- [`DocLinkStore`](../../types/DocLinkStore.md) — offline documentation/config-to-code links.

# Key Functions

- [`read_source_slice`](../../functions/read_source_slice.md) — read a line-range slice of a source file.

# Internal Helpers

Private helpers implement fuzzy symbol resolution
(`_resolve_symbol_candidates`, `_rank_symbol_candidates`,
`_levenshtein`, `_decompose_leaf`) and candidate summarization
(`_candidate_summary`); these are consumed by `SymbolStore.resolve_name`
(in `symbols.py`), which `EdgeStore.resolve_symbol_definition` delegates to.
