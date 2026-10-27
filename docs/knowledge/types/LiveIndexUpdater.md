---
type: Class
title: "LiveIndexUpdater"
description: "Keeps a long-running daemon or MCP server's index current with the working tree by re-indexing debounced change batches and reloading caches."
resource: code_search/engine/index_service.py#LiveIndexUpdater
tags: [index, daemon, service, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/index_service.py
    id: source-code
---

# Overview

Wraps [`FileWatcher`](FileWatcher.md) so the daemon and the MCP server observe
edits without a second foreground process. A change batch is debounced by the
watcher, re-indexed incrementally with the discovery policy recorded at index
time, and followed by an in-memory reload of the vector index and search
caches. The orchestrator calls `FreshnessChecker.mark_clean()` at the end of
every successful run, so the stale flag clears without waiting for the
freshness TTL.

Defined in [`engine.index_service`](../modules/engine/index_service.md).

# Methods

| Method | Description |
|---|---|
| `__init__(comps, root_path=None, exclusion_patterns=None)` | Bind to an initialised component registry; defaults the root to the registry's index root |
| `root_path` | The directory being watched |
| `start()` | Start polling for changes in a background thread |
| `stop()` | Stop polling and wait for the watcher thread to exit |
| `reindex_once()` | Run one incremental index with the recorded discovery policy; returns the run result or `None` |
| `reload()` | Reload vectors and drop caches so the next query sees the new index |

# Concurrency

Re-index runs are serialised: a batch that arrives while another run is in
flight waits for it instead of starting a second writer, so the index is never
written by two threads at once.

# See Also

[`IndexChangeDetector`](IndexChangeDetector.md) for the single-shot
change/reload decision used by long-running readers.
