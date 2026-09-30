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
[`engine.index_service`](../modules/engine/index_service.md); consumed by
[`build_response`](../functions/build_response.md).

# Methods

| Method | Description |
|---|---|
| `__init__(metadata: IndexMetadata \| None = None) -> None` | Create a change detector, optionally seeded with existing metadata. |
| `from_metadata_store(metadata_store: Any) -> IndexChangeDetector` | Build a detector seeded with the index state the process loaded. |
| `metadata: IndexMetadata` (property) | Get current index metadata. |
| `detect_index_change(new_mtime: Any) -> dict[str, Any]` | Detect if the index has changed based on new mtime. |
| `mark_reload_complete(metadata_store: Any \| None = None) -> IndexMetadata` | Mark the reload as complete and update status. |
