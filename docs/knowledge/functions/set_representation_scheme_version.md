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
[`engine.embeddings`](../modules/engine/embeddings.md).

# Signature

`def set_representation_scheme_version(metadata_store: Any, version: int \| None = None) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `Any` | The index metadata store, or `None` to no-op. |
| `version` | `int \| None` | The scheme to record; defaults to the running code's `REPRESENTATION_SCHEME_VERSION`. |

# Returns

None.
