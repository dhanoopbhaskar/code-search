---
type: Class
title: "GraphDatabase"
description: "Thread-safe SQLite database connection manager for the code graph schema."
resource: code_search/engine/graph.py#GraphDatabase
tags: [graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Thread-safe SQLite database connection manager for the code graph schema.
Defined in [`engine.graph`](../modules/engine/graph.md). The current
`SCHEMA_VERSION` is 16; `initialize()` migrates older databases forward.
v14 added the `module_edges`, `symbol_rationale` + `rationale_fts`, and
`doc_links` tables; v15 added `code_chunks.is_test` with its composite
index; v16 replaced the unique conventional-FQN index with a non-unique one
so legitimate duplicate symbols are no longer dropped.

# Methods

| Method | Description |
|---|---|
| `__init__(db_path: Path, settings: Settings \| None = None) -> None` | Initialize a thread-safe connection manager for *db_path*. |
| `initialize() -> None` | Create all tables, indexes, and triggers; record or validate schema version. |
| `connect() -> Generator[sqlite3.Connection, Any, None]` | Yield the calling thread's read connection in a context manager. |
| `write_transaction() -> Generator[sqlite3.Connection, Any, None]` | Yield a serialised write connection, committing on clean exit. |
| `write_connection() -> Generator[sqlite3.Connection, Any, None]` | Yield one serialised writer connection that spans many commits; the caller commits between batches, and clean exit commits and closes. |
| `set_fts_triggers(enabled: bool) -> None` | Drop (`False`) or recreate (`True`) the `chunks_fts` maintenance triggers; full builds suspend them while bulk-inserting and rebuild the index afterwards. |
| `rebuild_fts() -> int` | Clear and repopulate `chunks_fts` from `code_chunks`. |
| `fts_count() -> int` | Return the number of rows currently in `chunks_fts`. |
| `run_post_index_maintenance(*, full_rebuild: bool) -> None` | Optimize FTS5 segments, `ANALYZE`, truncate the WAL, and (on a full rebuild) `VACUUM`; failures are logged because the index is already committed. |
| `close() -> None` | Close the calling thread's cached connection, if any. |
