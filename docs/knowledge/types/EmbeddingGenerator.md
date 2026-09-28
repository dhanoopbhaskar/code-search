---
type: Class
title: "EmbeddingGenerator"
description: "Wraps the Model2Vec (potion-code-16m-32d) model to generate text embeddings with warm-up tracking."
resource: src/engine/embeddings.py#EmbeddingGenerator
tags: [embeddings, model2vec, model]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Wraps the Model2Vec `potion-code-16m-32d` model to generate text
embeddings, with lazy loading and warm-up-state tracking (see
[`WarmupState`](/types/WarmupState.md)). Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, model_path: Path, settings: Settings \| None = None) -> None` | Initialize generator; model is loaded lazily on first use. |
| `embed(self, text: str) -> list[float]` | Return the embedding vector for a single string. |
| `embed_batch(self, texts: list[str]) -> list[list[float]]` | Return embedding vectors for a batch of strings. |
| `is_loaded() -> bool` | Return whether the underlying model has been loaded into memory. |
| `warmup() -> None` | Run a throwaway inference call to force model load and JIT warm-up. |
