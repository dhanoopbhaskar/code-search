---
type: Function
title: "check_index_representation_compatibility"
description: "Raise when stored embeddings predate the running representation scheme."
resource: src/engine/embeddings.py#check_index_representation_compatibility
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Raises an error when the index's stored embeddings were generated under
an older `REPRESENTATION_SCHEME_VERSION` than the one currently running,
signalling that a re-index is required. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Signature

`def check_index_representation_compatibility(metadata_store: IndexMetadataStore, current_version: int) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `IndexMetadataStore` | Metadata store recording the index's build-time scheme version. |
| `current_version` | `int` | The currently running `REPRESENTATION_SCHEME_VERSION`. |

# Raises

`RuntimeError` when the stored version is older than *current_version*.
