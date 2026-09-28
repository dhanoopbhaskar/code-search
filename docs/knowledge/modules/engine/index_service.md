---
type: Module
title: "engine.index_service"
description: "Server-side change detection for index staleness via mtime tracking."
resource: src/engine/index_service.py
tags: [engine, freshness, server]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/index_service.py
    id: source-code
---

# Overview

Server-side change detection for index staleness via mtime tracking.
Compares the index's build timestamp (`last_indexed_at` in metadata)
against a refreshed or reloaded value, decides whether a reload is
needed, and generates a user-visible "index changed — restart required"
envelope when applicable.

# Key Classes

- [`IndexChangeDetector`](/types/IndexChangeDetector.md) — tracks index metadata (version, mtime, status) and decides reload vs. envelope response on detecting mtime changes.

# Key Functions

- [`index_mtime`](/functions/index_mtime.md) — extract the index's last build time from the metadata store.
