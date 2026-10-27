---
type: Module
title: "engine.index_service"
description: "Server-side index liveness: change detection from index mtime and the live incremental updater that keeps a daemon or MCP server current with the working tree."
resource: code_search/engine/index_service.py
tags: [engine, freshness, server]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/index_service.py
    id: source-code
---

# Overview

Two related services for readers that outlive a single invocation.

**Change detection.** Compares the index's build timestamp (`last_indexed_at`
in metadata) against a refreshed or reloaded value, decides whether a reload is
needed, and generates a user-visible "index changed — restart required"
envelope when applicable.

**Live updating.** [`LiveIndexUpdater`](../../types/LiveIndexUpdater.md) wraps
[`FileWatcher`](../../types/FileWatcher.md) so a daemon or MCP server observes
edits, re-indexes them incrementally with the discovery policy recorded at index
time, and reloads vectors and search caches afterwards. Runs are serialised and
`FreshnessChecker.mark_clean()` is called on success, so the stale flag clears
without waiting for the freshness TTL.

# Key Classes

- [`IndexChangeDetector`](../../types/IndexChangeDetector.md) — tracks index metadata (version, mtime, status) and decides reload vs. envelope response on detecting mtime changes.
- [`LiveIndexUpdater`](../../types/LiveIndexUpdater.md) — watches the working tree, re-indexes debounced batches, and reloads caches.

# Key Functions

- [`index_mtime`](../../functions/index_mtime.md) — extract the index's last build time from the metadata store.
