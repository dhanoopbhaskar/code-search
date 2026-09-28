---
type: Module
title: "engine.index_metadata"
description: "Tracks index version, mtime, timestamp, and status for server-side change detection."
resource: src/engine/index_metadata.py
tags: [engine, freshness, metadata]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_metadata.py
    id: source-code
---

# Overview

Tracks index version, mtime, timestamp, and status for server-side change
detection. Enables detection of index rebuilds and provides lifecycle
transitions (`CURRENT`/`STALE`/`UNAVAILABLE`) for reload envelopes or
status hints.

# Key Classes

- [`IndexStatus`](/types/IndexStatus.md) — `Enum` for index health status (`CURRENT`, `STALE`, `UNAVAILABLE`).
- [`IndexMetadata`](/types/IndexMetadata.md) — metadata tracking for index change detection (version, mtime, timestamp, status).
