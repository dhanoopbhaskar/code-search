---
type: Function
title: "get_representation_scheme_version"
description: "Read the stored chunk-representation scheme version from index metadata."
resource: src/engine/embeddings.py#get_representation_scheme_version
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Reads the stored chunk-representation scheme version
(`REPRESENTATION_SCHEME_VERSION`) from index metadata, used to detect
stale embeddings. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Signature

`def get_representation_scheme_version(metadata_store: IndexMetadataStore) -> int \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `IndexMetadataStore` | Metadata store to read from. |

# Returns

The stored scheme version, or `None` if never set.
