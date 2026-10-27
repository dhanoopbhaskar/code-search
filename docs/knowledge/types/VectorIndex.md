---
type: Class
title: "VectorIndex"
description: "In-memory/on-disk vector index for cosine-similarity nearest-neighbor search over chunk embeddings, with legacy JSON or compact binary metadata."
resource: code_search/engine/embeddings.py#VectorIndex
tags: [embeddings, vector-search, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

Vector index for cosine-similarity nearest-neighbor search over chunk
embeddings, persisted alongside the SQLite index. Defined in
[`engine.embeddings`](../modules/engine/embeddings.md); consumed by
[`VectorSearch`](VectorSearch.md).

In compact mode the metadata sidecar is a `CSVMETA1` header followed by
packed `(chunk_id, file_id, content_type)` rows, with file paths appended
to a sibling `.files` NDJSON dictionary. Path and content filters then run
as numpy masks, and saves append only new rows. Legacy JSON v2 sidecars are
accepted and migrate on the next save.

# Methods

| Method | Description |
|---|---|
| `__init__(vectors_bin_path: Path, vectors_meta_path: Path, removed_path: Path \| None = None, compact: bool = False) -> None` | Initialize an in-memory vector index backed by three on-disk files; *compact* selects the binary sidecar. |
| `load() -> None` | Load vectors, metadata, and tombstones from disk, if they exist. |
| `set_path_lookup(lookup: Any, bulk_lookup: Any = None) -> None` | Attach `chunk_id -> file_path` resolvers used by compact metadata, with an optional bulk resolver for legacy rows. |
| `save() -> None` | Persist the delta since the last save (appended rows + tombstones). |
| `add(chunk_id: int, embedding: np.ndarray, metadata: dict[str, Any]) -> int` | Append one vector + metadata entry and return its physical index. |
| `add_batch(chunk_ids: list[int], embeddings: list[np.ndarray], metadata_list: list[dict[str, Any]]) -> list[int]` | Append multiple vectors + metadata entries atomically. |
| `search(query_embedding: np.ndarray, top_k: int = 10, exclude_file_paths: set[str] \| None = None, content: str = 'all') -> list[tuple[int, float]]` | Cosine-similarity search — returns `(chunk_id, score)` sorted descending. |
| `size: int` (property) | Return the number of alive vectors currently in the index. |
| `remove(chunk_id: int) -> bool` | Remove the vector + metadata entry for *chunk_id* by tombstoning it. |
| `remove_many(chunk_ids: list[int]) -> int` | Tombstone every alive vector whose chunk id is in *chunk_ids*. |
| `clear() -> None` | Drop all vectors and metadata, truncating the on-disk files. |
