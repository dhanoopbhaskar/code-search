---
type: Function
title: "index_mtime"
description: "Extract the index's last build time from the metadata store."
resource: code_search/engine/index_service.py#index_mtime
tags: [freshness, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/index_service.py
    id: source-code
---

# Overview

Extracts the index's last build time from the metadata store, used by
[`IndexChangeDetector`](../types/IndexChangeDetector.md). Defined in
[`engine.index_service`](../modules/engine/index_service.md).

# Signature

`def index_mtime(metadata_store: Any) -> datetime \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `metadata_store` | `Any` | The `IndexMetadataStore` exposing `get`. |

# Returns

The parsed build time, or `None` when unset/unparseable.
