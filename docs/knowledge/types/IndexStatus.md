---
type: Class
title: "IndexStatus"
description: "Enum for index health status (CURRENT, STALE, UNAVAILABLE)."
resource: code_search/engine/index_metadata.py#IndexStatus
tags: [freshness, metadata, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/index_metadata.py
    id: source-code
---

# Overview

`Enum` for index health status: `CURRENT`, `STALE`, or `UNAVAILABLE`.
Defined in
[`engine.index_metadata`](../modules/engine/index_metadata.md); a field of
[`IndexMetadata`](IndexMetadata.md).

# Values

| Value | Description |
|---|---|
| `CURRENT` | Index is up to date. |
| `STALE` | Index mtime differs from the loaded state. |
| `UNAVAILABLE` | Index metadata unavailable or not yet built. |
