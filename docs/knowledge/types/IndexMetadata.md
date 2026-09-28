---
type: Class
title: "IndexMetadata"
description: "Metadata tracking for index change detection (version, mtime, timestamp, status)."
resource: src/engine/index_metadata.py#IndexMetadata
tags: [freshness, metadata, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_metadata.py
    id: source-code
---

# Overview

Metadata tracking for index change detection, enabling detection of index
rebuilds since a serving process last loaded the index. Defined in
[`engine.index_metadata`](/modules/engine/index_metadata.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `version` | `str` | Index schema/build version. |
| `mtime` | `float` | Last modification time of the index build. |
| `timestamp` | `str` | ISO timestamp of the last index build. |
| `status` | `IndexStatus` | Current health status of the index. |
