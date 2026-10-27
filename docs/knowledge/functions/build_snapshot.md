---
type: Function
title: "build_snapshot"
description: "Read one index generation into a compact adjacency snapshot."
resource: code_search/engine/graph_cache.py#build_snapshot
tags: [engine, function, graph_cache]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

Read one index generation into a compact adjacency snapshot.

Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md).

# Signature

`def build_snapshot(db: GraphDatabase, generation: str) -> GraphSnapshot`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to read. |
| `generation` | The generation token the snapshot describes. |

# Returns

A `GraphSnapshot`. The database must already have the v18 symbol columns; `initialize` migrates them.
