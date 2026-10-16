---
type: Function
title: "check_index_representation_compatibility"
description: "Raise when stored embeddings predate the running representation scheme."
resource: code_search/engine/embeddings.py#check_index_representation_compatibility
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

Raises an error when the index's stored embeddings were generated under
an older `REPRESENTATION_SCHEME_VERSION` than the one currently running,
signalling that a re-index is required. Defined in
[`engine.embeddings`](../modules/engine/embeddings.md).

# Signature

`def check_index_representation_compatibility(metadata_store: Any, *, has_vectors: bool = False) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `Any` | The index metadata store, or `None` when unavailable. |
| `has_vectors` | `bool` | Whether the vector index currently holds any vectors. |

# Raises

ValueError: When the stored scheme differs from the running code, or the marker is absent on an engine-built vector-bearing index.
