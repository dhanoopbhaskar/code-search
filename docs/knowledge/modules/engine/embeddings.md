---
type: Module
title: "engine.embeddings"
description: "Model2Vec embedding generation and flat-file vector index with cosine search and tombstone-based removal."
resource: src/engine/embeddings.py
tags: [engine, embeddings, vector-search]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Provides vector embedding generation and flat-file vector index
operations for code search. Uses Model2Vec's `StaticModel` to generate
fixed-dimension dense vectors from code text, persisted as binary numpy
arrays with JSON metadata sidecars. Handles embedding model lifecycle
(cold start, warming, caching), compatibility checks across index
rebuilds, and cosine-similarity search with tombstone-based removal
semantics.

# Key Constants

| Constant | Purpose |
|---|---|
| `WarmupState` | Enum of model lifecycle states: `COLD`, `WARMING`, `WARM`, `FAILED`, `DISABLED` |
| `RANKED_PATH_HYBRID` / `_LEXICAL_REDUCED` / `_LEXICAL_DEGRADED` | Ranked-path identifiers surfaced in responses |
| `MODEL_NAME` | Default model: `"potion-code-16m-32d"` |
| `EMBEDDING_DIM` | Default embedding dimension: `32` |

# Key Classes

- [`WarmupState`](/types/WarmupState.md) — lifecycle state enum for the embedding model.
- [`EmbeddingGenerator`](/types/EmbeddingGenerator.md) — generates normalised vector embeddings for code text.
- [`VectorIndex`](/types/VectorIndex.md) — flat numpy-based vector store with O(1) tombstone removal.

# Key Functions

- [`profile_model_available`](/functions/profile_model_available.md) — whether the active model profile is available locally.
- [`check_index_model_compatibility`](/functions/check_index_model_compatibility.md) — raise when the index was built by a different embedding model.
- [`get_representation_scheme_version`](/functions/get_representation_scheme_version.md), [`set_representation_scheme_version`](/functions/set_representation_scheme_version.md) — track the chunk-representation scheme version.
- [`check_index_representation_compatibility`](/functions/check_index_representation_compatibility.md) — raise when stored embeddings predate the running representation scheme.

# Internal Helpers

Model path discovery (`_find_local_model_path`, `_get_binary_dir`,
`_get_user_base`), persisted load-state tracking
(`_check_persistent_model_state`, `_persist_model_state`,
`_get_metadata_store`), and the module-level singleton loader
(`_load_model`).
