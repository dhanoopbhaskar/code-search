---
type: Module
title: "engine.graph_cache"
description: "Generation-keyed in-memory CSR adjacency cache for the symbol graph, bounded by a byte budget and falling back to SQL on any failure."
resource: code_search/engine/graph_cache.py
tags: [engine, graph, cache, performance]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

The graph lives in SQLite. Answering a multi-hop question with one query per
visited node makes latency a function of the node count instead of the edge
count, so this module materialises the resolved symbol edges once per index
generation into compact arrays and lets a walk read neighbour slices from
memory.

The layout is a compressed sparse row (CSR) array per direction plus a symbol
directory dict — no third-party graph library.

# Design Constraints

- **Generation-keyed.** The cache key is `(database path, index_generation)`. A
  reindex publishes a new generation, which makes the old snapshot
  unreachable; a committed write drops the entry eagerly via
  [`invalidate_adjacency_cache`](../../functions/invalidate_adjacency_cache.md).
- **Bounded.** A snapshot reports its estimated size. A snapshot above the
  configured budget (`CODE_SEARCH_GRAPH_CACHE_MAX_BYTES`, derived from available
  memory) is refused and remembered as over-budget instead of being silently
  kept; idle entries expire after
  `CODE_SEARCH_GRAPH_CACHE_IDLE_SECONDS`. `CODE_SEARCH_GRAPH_CACHE_ENABLED=false`
  disables the cache entirely.
- **Best effort.** Any build failure falls back to the SQL path. The cache is an
  optimisation, never a correctness requirement.
- **Resolved structure only.** Unresolved references are evidence, not graph
  structure, so only edges with a target participate. Containment (`CONTAINS`)
  comes from `symbols.parent_symbol_id` and is always available.

# Public API

- [`read_index_generation`](../../functions/read_index_generation.md),
  [`build_snapshot`](../../functions/build_snapshot.md) — read one generation
  into a [`GraphSnapshot`](../../types/GraphSnapshot.md).
- [`adjacency_snapshot`](../../functions/adjacency_snapshot.md) — return the
  current snapshot from the process-wide cache when usable.
- [`invalidate_adjacency_cache`](../../functions/invalidate_adjacency_cache.md),
  [`adjacency_cache_stats`](../../functions/adjacency_cache_stats.md),
  [`clear_adjacency_cache`](../../functions/clear_adjacency_cache.md) — lifecycle
  and diagnostics.

# Types

[`GraphSnapshot`](../../types/GraphSnapshot.md),
[`AdjacencyCache`](../../types/AdjacencyCache.md),
[`CachedSymbol`](../../types/CachedSymbol.md),
[`CachedNeighbor`](../../types/CachedNeighbor.md).

# Consumers

[`engine.graph_query`](graph_query.md) reads the snapshot for neighbourhood and
shortest-path walks, and [`engine.graph_surface`](graph_surface.md) reports the
cache state through graph-schema diagnostics.
