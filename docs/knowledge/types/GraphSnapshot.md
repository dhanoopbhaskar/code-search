---
type: Class
title: "GraphSnapshot"
description: "Read-only, in-memory CSR view of one index generation's symbol adjacency, with per-direction neighbours and containment lookups."
resource: code_search/engine/graph_cache.py#GraphSnapshot
tags: [graph, cache, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

A snapshot holds the resolved edges of exactly one published index generation as
compressed sparse row arrays grouped in ascending symbol-id order. `_ids` is the
sorted id array used to map a symbol id to its row by binary search, so a lookup
needs no second dict.

Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md); built by
[`build_snapshot`](../functions/build_snapshot.md) and served from the
process-wide [`AdjacencyCache`](AdjacencyCache.md).

# State

| Group | Contents |
|---|---|
| `generation`, `edge_count` | The generation token the snapshot describes and how many resolved edges it holds |
| `out_*` / `in_*` | `indptr`, `other` (neighbour id), `type` (type code), `tier` (tier code) arrays per direction |
| `child_*` | Containment CSR derived from `symbols.parent_symbol_id` |
| `_symbols` | Directory of [`CachedSymbol`](CachedSymbol.md) entries |
| `_type_names`, `_tier_names`, `_type_codes` | Compact code → name tables |

# Methods

| Method | Description |
|---|---|
| `symbol_count` | Number of symbols in the snapshot |
| `estimated_bytes` | Estimated resident size, used for the cache budget |
| `symbol(symbol_id)` | Directory entry for a symbol, or `None` |
| `type_codes(edge_types)` | Translate edge-type names to compact codes; unknown names are ignored and an empty input yields an empty set |
| `iter_out(symbol_id, type_codes=None)` | Yield outgoing [`CachedNeighbor`](CachedNeighbor.md) rows in stored order |
| `iter_in(symbol_id, type_codes=None)` | Yield incoming neighbours in stored order |
| `children(symbol_id)` | Yield declared child symbol ids |
| `parent(symbol_id)` | Declaring parent symbol id, if any |

# Guarantees

Only edges with a resolved target participate, and iteration order follows the
stored order, so a traversal over a snapshot is reproducible. The snapshot is
immutable once built; a new generation produces a new snapshot rather than
mutating the old one.
