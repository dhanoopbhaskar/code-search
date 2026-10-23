---
type: Module
title: "engine.embeddings"
description: "Model2Vec embedding generation and flat-file vector index with cosine search, compact binary metadata, and tombstone-based removal."
resource: code_search/engine/embeddings.py
tags: [engine, embeddings, vector-search]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

Provides vector embedding generation and flat-file vector index
operations for code search. Uses Model2Vec's `StaticModel` to generate
fixed-dimension dense vectors from code text, persisted as binary numpy
arrays with metadata sidecars. Handles embedding model lifecycle
(cold start, warming, caching), compatibility checks across index
rebuilds, and cosine-similarity search with tombstone-based removal
semantics.

Two metadata layouts are supported. The legacy layout stores one JSON
entry per chunk (`vectors.meta.json`). The compact layout
(`CODE_SEARCH_INDEX_LAYOUT=compact`, the `small` runtime profile default)
writes `vectors.v2.meta` as a fixed `CSVMETA1` header followed by packed
`(chunk_id, file_id, content_type)` rows, plus an append-only
`vectors.v2.meta.files` NDJSON dictionary. Path and content filters then run
as numpy masks, and an incremental save appends only newly added rows.
Existing JSON v2 sidecars migrate on the next save, and rows without a file
id are resolved through one bulk chunk-path lookup instead of a query per
chunk.

# Key Constants

| Constant | Purpose |
|---|---|
| `WarmupState` | Enum of model lifecycle states: `COLD`, `WARMING`, `WARM`, `FAILED`, `DISABLED` |
| `RANKED_PATH_HYBRID` / `RANKED_PATH_LEXICAL_REDUCED` / `RANKED_PATH_LEXICAL_DEGRADED` | Ranked-path identifiers surfaced in responses |
| `MODEL_NAME` | Default model: `"potion-code-16m-32d"` |
| `EMBEDDING_DIM` | Default embedding dimension: `32` |
| `_COMPACT_META_MAGIC` / `_COMPACT_META_HEADER` | Compact sidecar magic (`CSVMETA1`) and `<8sII` version/count header. |
| `_COMPACT_ROW_DTYPE` | Packed row dtype: `chunk_id` (`<i4`), `file_id` (`<i4`), `content_type` (`<i1`). |

# Key Classes

- [`WarmupState`](../../types/WarmupState.md) — lifecycle state enum for the embedding model.
- [`EmbeddingGenerator`](../../types/EmbeddingGenerator.md) — generates normalised vector embeddings for code text.
- [`VectorIndex`](../../types/VectorIndex.md) — flat numpy-based vector store with O(1) tombstone removal.

# Key Functions

- [`profile_model_available`](../../functions/profile_model_available.md) — whether the active model profile is available locally.
- [`check_index_model_compatibility`](../../functions/check_index_model_compatibility.md) — raise when the index was built by a different embedding model.
- [`get_representation_scheme_version`](../../functions/get_representation_scheme_version.md), [`set_representation_scheme_version`](../../functions/set_representation_scheme_version.md) — track the chunk-representation scheme version.
- [`check_index_representation_compatibility`](../../functions/check_index_representation_compatibility.md) — raise when stored embeddings predate the running representation scheme.

# Internal Helpers

Model path discovery (`_find_local_model_path`, `_get_binary_dir`,
`_get_user_base`), persisted load-state tracking
(`_check_persistent_model_state`, `_persist_model_state`,
`_get_metadata_store`), and the module-level singleton loader
(`_load_model`). Compact sidecar plumbing is split across
`_load_compact_metadata`, `_read_compact_meta` (accepts binary v1 and legacy
JSON v2), `_read_files`, `_save_compact_meta` (append or rewrite),
`_rewrite_compact_meta`, `_append_compact_files`, and
`_resolve_compact_file_ids_bulk`.
