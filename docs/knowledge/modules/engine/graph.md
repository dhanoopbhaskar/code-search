---
type: Module
title: "engine.graph"
description: "SQLite schema and CRUD layer for the code graph: symbols, typed edges, code chunks (FTS5), corpus statistics, and index metadata."
resource: code_search/engine/graph.py
tags: [engine, graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

SQLite-backed schema and CRUD layer for the code graph: symbols
(function/class/method definitions with FQN, location, docstring), typed
directed edges (`CALLS`, `IMPORTS`, `INHERITS`, `IMPLEMENTS`, `REFERENCES`,
`USAGE`, `CALL_REFERENCE`, `TESTS`), code chunks with FTS5 full-text search,
file-level `module_edges`, rationale comments (`symbol_rationale` with
`rationale_fts`), offline `doc_links`, derived symbol degrees
(`symbol_degrees`), per-generation coverage (`index_coverage`), persisted
corpus statistics (`subword_stats`/`prefix_stats`), and index metadata
(version, status, counts). Provides thread-safe database access via
per-thread connections, forward-migration logic for older schema versions,
and high-level graph traversal (call graph, inheritance tree, symbol
resolution).

Edge rows carry a JSON `properties` object with resolution evidence (`via`,
`line`, `arg_count`, `candidate_count`). Symbols carry `canonical_fqn`,
`visibility`, `is_test`, `is_entry_point`, `entry_point_reason`, and
`importance`, all computed by the post-index trust passes.

Chunks carry an `is_test` flag with an `(is_test, content_type)` index so
the production/test match split avoids rescanning paths. Conventional FQNs
use a non-unique index: the same class can legitimately appear in multiple
source roots, and a field can share its name with a no-arg accessor, so
uniqueness would silently drop symbols.

# Key Constants

`SCHEMA_VERSION = 18` — current schema target version (v15 added
`is_test`; v16 replaced the unique conventional-FQN index with a non-unique
one; v17 deduplicated unresolved edges and added `index_coverage`; v18 added
edge `properties`, the `IMPLEMENTS`/`USAGE`/`CALL_REFERENCE`/`TESTS` edge
types, `symbol_degrees`, and the symbol trust columns). `SUBWORD_STATS_TABLE_DDL`, `PREFIX_STATS_TABLE_DDL`, `STATS_INDEXES` —
persisted document-frequency tables rebuilt at the end of each index run.
`SYMBOLS_TABLE_DDL`,
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
Resolution first runs indexed exact lookups and only falls back to
leading-wildcard suffix matching when no exact row exists.

`_migrate_v16` replaces the unique conventional-FQN index, and
[`run_post_index_maintenance`](../../types/GraphDatabase.md) performs
`chunks_fts` optimize, `ANALYZE`, WAL truncation, and (on a full rebuild)
`VACUUM`.
