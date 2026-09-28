---
type: Class
title: "GraphDatabase"
description: "Thread-safe SQLite database connection manager for the code graph schema."
resource: src/engine/graph.py#GraphDatabase
tags: [graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/graph.py
    id: source-code
---

# Overview

Thread-safe SQLite database connection manager for the code graph schema.
Defined in [`engine.graph`](/modules/engine/graph.md). Manages 13+ schema
version migrations.

# Methods

| Method | Description |
|---|---|
| `__init__(self, db_path: Path, settings: Settings \| None = None) -> None` | Initialize a thread-safe connection manager; connections created lazily per-thread. |
| `initialize() -> None` | Create all tables, indexes, and triggers; record or validate schema version; handle migrations. |
| `connect() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding the calling thread's read-only connection. |
| `write_transaction() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding a serialised write connection; commits on clean exit. |
| `rebuild_fts() -> int` | Clear and repopulate `chunks_fts` from `code_chunks`; return resulting row count. |
| `fts_count() -> int` | Return the number of rows currently in `chunks_fts`. |
| `close() -> None` | Close the calling thread's cached connection, if any. |
