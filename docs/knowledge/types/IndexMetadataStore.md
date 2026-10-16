---
type: Class
title: "IndexMetadataStore"
description: "Key-value store for index metadata (status, version, counts, etc.)."
resource: code_search/engine/graph.py#IndexMetadataStore
tags: [graph, metadata, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Key-value store for index metadata (status, version, counts, etc.).
Defined in [`engine.graph`](../modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase) -> None` | Initialize the metadata store over a graph database. |
| `get(key: str) -> str \| None` | Return the string value for *key*, or `None` when unset. |
| `get_int(key: str) -> int \| None` | Return the integer value for *key*, or `None` when unset. |
| `get_json(key: str) -> Any` | Return the JSON-decoded value for *key*, or `None` when unset. |
| `set(key: str, value: str) -> None` | Upsert the string *value* under *key*. |
| `set_int(key: str, value: int) -> None` | Upsert the integer *value* under *key*. |
| `set_json(key: str, value: Any) -> None` | JSON-serialise *value* and upsert it under *key*. |
| `get_all() -> dict[str, str]` | Return every key/value pair currently stored. |
| `get_index_status() -> str` | Return the lifecycle `index_status` value (default `unindexed`). |
| `set_index_status(status: str) -> None` | Set the lifecycle `index_status`, validating against the fixed vocabulary (`unindexed`, `indexing`, `ready`, `stale`, `error`). |
| `get_fts_chunks() -> int \| None` | Return the recorded `chunks_fts` row count, or `None` if unset. |
| `set_fts_chunks(count: int) -> None` | Record the number of rows in `chunks_fts` for parity verification. |
