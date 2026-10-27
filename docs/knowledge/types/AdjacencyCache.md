---
type: Class
title: "AdjacencyCache"
description: "Thread-safe LRU registry of generation-keyed graph snapshots with a byte budget, idle expiry, and hit/miss/build counters."
resource: code_search/engine/graph_cache.py#AdjacencyCache
tags: [graph, cache, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

One process-wide instance (`_CACHE`) hands out
[`GraphSnapshot`](GraphSnapshot.md) objects keyed by `(database path,
index_generation)`. A reindex publishes a new generation, which makes the old
entry unreachable; a committed write drops it eagerly.

Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md).

# Methods

| Method | Description |
|---|---|
| `get(db, settings)` | Return a snapshot for the database's current generation, building one if absent and the budget allows |
| `invalidate(db_path)` | Drop every snapshot for a database path |
| `clear()` | Drop every snapshot and reset the hit/miss counters |
| `stats()` | Return cache diagnostics (entries, over-budget keys, hits, misses, builds) |

# Policy

- A snapshot whose estimated size exceeds `graph_cache_max_bytes` is refused
  and recorded in `_over_budget`, so a too-large graph is not rebuilt on every
  query.
- Entries idle for longer than `graph_cache_idle_seconds` are evicted, so a
  daemon serving several repositories does not keep every snapshot resident.
- All mutation happens under a re-entrant lock, and a build failure is treated
  as a miss: the caller falls back to SQL.
