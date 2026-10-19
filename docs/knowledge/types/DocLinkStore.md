---
type: Class
title: "DocLinkStore"
description: "CRUD for offline links between documentation/config chunks and code chunks."
resource: code_search/engine/graph.py#DocLinkStore
tags: [graph, database, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Stores rows of the `doc_links` table (`doc_chunk_id`, `code_chunk_id`,
`score`, `method`), computed offline at index time from local embeddings and
deterministic symbol mentions when `CODE_SEARCH_INDEX_DOC_LINKS` is enabled
(see [environment](../config/environment.md)). Read by
[`GraphQueryService.explain`](GraphQueryService.md). Defined in
[`engine.graph`](../modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase) -> None` | Initialize the store over *db*. |
| `insert_batch(rows: list[dict[str, Any]], conn: sqlite3.Connection \| None = None) -> None` | Insert doc links, ignoring duplicates. |
| `for_code_chunk(code_chunk_id: int, limit: int = 5) -> list[dict[str, Any]]` | Documentation linked to a code chunk, best score first. |
| `for_file(file_path: str, limit: int = 10) -> list[dict[str, Any]]` | Links whose code chunk lives in *file_path*. |
