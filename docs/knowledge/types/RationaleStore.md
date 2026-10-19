---
type: Class
title: "RationaleStore"
description: "CRUD and full-text search for rationale comments linked to symbols."
resource: code_search/engine/graph.py#RationaleStore
tags: [graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Persists `NOTE`/`WHY`/`HACK`/`TODO`/`FIXME`/ADR comment lines in the
`symbol_rationale` table, each attached to the nearest enclosing symbol and
indexed by the `rationale_fts` FTS5 table. Rows are produced at index time by
[`IndexOrchestrator`](IndexOrchestrator.md) and surfaced through
[`GraphQueryService.explain`](GraphQueryService.md). Defined in
[`engine.graph`](../modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase) -> None` | Initialize the store over *db*. |
| `insert_batch(rows: list[dict[str, Any]], conn: sqlite3.Connection \| None = None) -> None` | Insert rows carrying `symbol_id`, `file_path`, `line_start`, `line_end`, `kind`, and `text`, ignoring duplicates. |
| `for_symbol(symbol_id: int, limit: int = 20) -> list[dict[str, Any]]` | Rationale attached to a symbol, ordered by line. |
| `for_file(file_path: str, limit: int = 50) -> list[dict[str, Any]]` | Rationale in a file, ordered by line. |
| `search(query: str, limit: int = 10) -> list[dict[str, Any]]` | Full-text search over rationale comments via `rationale_fts`. |
