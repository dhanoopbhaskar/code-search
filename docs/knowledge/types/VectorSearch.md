---
type: Class
title: "VectorSearch"
description: "Semantic search using the vector index."
resource: src/engine/search.py#VectorSearch
tags: [search, vector, semantic]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Semantic search using the vector index. Defined in
[`engine.search`](/modules/engine/search.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, vector_index: VectorIndex, embedding_generator: EmbeddingGenerator) -> None` | Initialize semantic search over the vector index and embedding generator. |
| `search(self, query: str, top_k: int = 10, content: str = "all") -> list[tuple[int, float]]` | Embed *query* and return `(chunk_id, cosine_score)` matches, scoped by content axis. |
