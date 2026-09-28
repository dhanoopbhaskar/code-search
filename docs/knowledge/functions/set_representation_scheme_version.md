---
type: Function
title: "set_representation_scheme_version"
description: "Persist the current chunk-representation scheme version into index metadata."
resource: src/engine/embeddings.py#set_representation_scheme_version
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Persists the current `REPRESENTATION_SCHEME_VERSION` into index metadata
after a (re)index build. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Signature

`def set_representation_scheme_version(metadata_store: IndexMetadataStore, version: int) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `IndexMetadataStore` | Metadata store to write to. |
| `version` | `int` | The current representation scheme version. |

# Returns

None.
