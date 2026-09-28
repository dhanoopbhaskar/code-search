---
type: Function
title: "index_mtime"
description: "Extract the index's last build time from the metadata store."
resource: src/engine/index_service.py#index_mtime
tags: [freshness, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_service.py
    id: source-code
---

# Overview

Extracts the index's last build time from the metadata store, used by
[`IndexChangeDetector`](/types/IndexChangeDetector.md). Defined in
[`engine.index_service`](/modules/engine/index_service.md).

# Signature

`def index_mtime(metadata_store: IndexMetadataStore) -> float \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `IndexMetadataStore` | Metadata store to read from. |

# Returns

The index's last-build mtime, or `None` if unset.
