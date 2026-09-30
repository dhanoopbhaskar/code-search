---
type: Class
title: "IndexMetadata"
description: "Metadata tracking for index change detection (version, mtime, timestamp, status)."
resource: src/engine/index_metadata.py#IndexMetadata
tags: [freshness, metadata, class]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_metadata.py
    id: source-code
---

# Overview

Metadata tracking for index change detection, enabling detection of index
rebuilds since a serving process last loaded the index. Defined in
[`engine.index_metadata`](../modules/engine/index_metadata.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `version` | `str` | Index schema version (default `1.0.0`) recorded in the metadata. |
| `mtime` | `datetime \| None` | Modification time of the index files; used by server to detect changes. |
| `timestamp` | `datetime \| None` | UTC timestamp when the index was last built/updated. |
| `status` | `IndexStatus \| None` | Current index health status. |

# Methods

| Method | Description |
|---|---|
| `to_dict() -> dict[str, Any]` | Serialize the metadata to a plain dict (ISO timestamps, enum value). |
| `from_dict(data: dict[str, Any]) -> IndexMetadata` | Build metadata from a serialized dict. |
| `check_for_changes(new_mtime: datetime) -> dict[str, Any]` | Compare *new_mtime* to the stored mtime and return a `has_changed`/`old_status`/`new_status` descriptor. |
| `update_mtime(new_mtime: datetime) -> IndexMetadata` | Set the mtime on this instance in place and return `self`. |
