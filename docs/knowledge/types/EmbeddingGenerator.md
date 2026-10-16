---
type: Class
title: "EmbeddingGenerator"
description: "Wraps the Model2Vec (potion-code-16m-32d) model to generate text embeddings with warm-up tracking."
resource: code_search/engine/embeddings.py#EmbeddingGenerator
tags: [embeddings, model2vec, model]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

Wraps the Model2Vec `potion-code-16m-32d` model to generate text
embeddings, with lazy loading and warm-up-state tracking (see
[`WarmupState`](WarmupState.md)). Defined in
[`engine.embeddings`](../modules/engine/embeddings.md).

# Methods

| Method | Description |
|---|---|
| `__init__(settings: Settings \| None = None, disabled: bool = False) -> None` | Initialize the generator with the settings governing model/dimension. |
| `is_available() -> bool` | Return whether the embedding model is loaded (or loadable). |
| `model_load_was_warm() -> bool` | Return whether a real model was already loaded before this request. |
| `warm_start() -> bool` | Eagerly load the vector model so the daemon holds it warm. |
| `begin_warmup() -> None` | Start loading the model in the background; safe to call repeatedly. |
| `is_warm() -> bool` | Return whether a real model is in memory; never blocks. |
| `warm_state() -> WarmupState` | Return the model lifecycle state; never blocks. |
| `wait_warm(timeout: float \| None = None) -> bool` | Wait up to *timeout* seconds for warmup to finish. |
| `reset_model() -> None` | Reset the model state to force a reload on next use. |
| `encode(text: str) -> np.ndarray \| None` | Encode a single text string into a normalised embedding vector. |
| `encode_batch(texts: list[str]) -> list[np.ndarray \| None]` | Encode a list of texts with one batched `model.encode` call. |
| `embedding_to_bytes(embedding: np.ndarray) -> bytes` | Serialise an embedding array to raw `float32` bytes. |
| `bytes_to_embedding(data: bytes) -> np.ndarray` | Deserialise raw `float32` bytes back into an embedding array. |
