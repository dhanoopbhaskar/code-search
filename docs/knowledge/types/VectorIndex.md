---
type: Class
title: "VectorIndex"
description: "In-memory/on-disk vector index for cosine-similarity nearest-neighbor search over chunk embeddings."
resource: src/engine/embeddings.py#VectorIndex
tags: [embeddings, vector-search, index]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Vector index for cosine-similarity nearest-neighbor search over chunk
embeddings, persisted alongside the SQLite index. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md); consumed by
[`VectorSearch`](/types/VectorSearch.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, index_dir: Path, dim: int) -> None` | Initialize an index of the given embedding dimensionality. |
| `add(self, chunk_id: int, vector: list[float]) -> None` | Add a single chunk vector to the index. |
| `add_batch(self, chunk_ids: list[int], vectors: list[list[float]]) -> None` | Add multiple chunk vectors at once. |
| `search(self, query_vector: list[float], top_k: int = 10) -> list[tuple[int, float]]` | Return the top-k `(chunk_id, cosine_score)` nearest neighbors. |
| `save() -> None` | Persist the index to disk. |
| `load() -> None` | Load the index from disk. |
| `size() -> int` | Return the number of vectors currently indexed. |
