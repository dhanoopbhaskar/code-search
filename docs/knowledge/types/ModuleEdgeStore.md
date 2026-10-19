---
type: Class
title: "ModuleEdgeStore"
description: "CRUD and reverse/forward traversal for file-level `module_edges` rows."
resource: code_search/engine/graph.py#ModuleEdgeStore
tags: [graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Stores file-to-file relations (currently `IMPORTS`) in the `module_edges`
table, kept apart from `graph_edges` so imports need no symbol node. Paths are
index-root-relative POSIX paths; unresolved imports are kept with
`resolved = 0` and their raw target. Rows are unique on
`(source_path, relation, target_path, target_raw)`. Populated by
[`IndexOrchestrator`](IndexOrchestrator.md) and read by
[`GraphQueryService`](GraphQueryService.md). Defined in
[`engine.graph`](../modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase) -> None` | Initialize the store over *db*. |
| `insert_edges_batch(edges: list[dict[str, Any]], conn: sqlite3.Connection \| None = None) -> None` | Insert module edges, ignoring duplicates; reuse *conn* when given, otherwise open and commit a transaction. |
| `get_importers(path: str, max_depth: int = 1) -> list[dict[str, Any]]` | Files that import *path* (reverse traversal, depth clipped to 5), as `{path, depth}` rows. |
| `get_imports(path: str, max_depth: int = 1) -> list[dict[str, Any]]` | Files imported by *path* (forward traversal). |
| `all_edges(relation: str = 'IMPORTS') -> list[dict[str, Any]]` | Every edge of *relation*, in deterministic order. |
| `resolution_stats(relation: str = 'IMPORTS') -> dict[str, int]` | `{total, resolved, unresolved}` counts for *relation*. |
