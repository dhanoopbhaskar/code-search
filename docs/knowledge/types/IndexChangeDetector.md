---
type: Class
title: "IndexChangeDetector"
description: "Tracks index metadata (version, mtime, status) and decides reload vs. envelope response on detecting mtime changes."
resource: src/engine/index_service.py#IndexChangeDetector
tags: [freshness, server]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_service.py
    id: source-code
---

# Overview

Tracks index metadata (version, mtime, status) and decides whether a
reload is needed or an "index changed — restart required" envelope
should be generated. Defined in
[`engine.index_service`](/modules/engine/index_service.md); consumed by
[`build_response`](/functions/build_response.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, metadata_store: IndexMetadataStore) -> None` | Initialize over an index metadata store. |
| `has_changed() -> bool` | Return whether the index's `last_indexed_at` mtime has changed since load. |
| `refresh() -> None` | Re-read the current mtime baseline after a reload. |
