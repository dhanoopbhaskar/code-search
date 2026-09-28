---
type: Function
title: "check_index_model_compatibility"
description: "Raise when the index was built by a different embedding model."
resource: src/engine/embeddings.py#check_index_model_compatibility
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Raises an error when the loaded index's recorded embedding model
identifier does not match the currently configured model, preventing
mixing incompatible vector spaces. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Signature

`def check_index_model_compatibility(metadata_store: IndexMetadataStore, current_model_name: str) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `IndexMetadataStore` | Metadata store recording the index's build-time model. |
| `current_model_name` | `str` | The currently configured embedding model name. |

# Raises

`RuntimeError` when the models differ.
