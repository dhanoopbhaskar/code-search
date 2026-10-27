---
type: Class
title: "CachedSymbol"
description: "Frozen symbol metadata record held in a graph snapshot's directory so a node can be shaped without another SQL query."
resource: code_search/engine/graph_cache.py#CachedSymbol
tags: [graph, cache, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

A frozen, slot-based dataclass mirroring the `symbols` columns a rendered graph
node needs. Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md)
and held by [`GraphSnapshot`](GraphSnapshot.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Symbol id (the snapshot's row key) |
| `fqn` | `str` | Stored fully qualified name |
| `name` | `str` | Declaration name |
| `kind` | `str` | Declaration kind (`function`, `method`, `class`, …) |
| `file_path` | `str` | Stored file path spelling |
| `line_start`, `line_end` | `int` | Declaration line range |
| `conventional_fqn` | `str \| None` | Path-independent name, when known |
| `docstring` | `str \| None` | Stored docstring |
| `parent_id` | `int \| None` | Declaring parent symbol id |
| `is_test` | `bool` | Whether the symbol lives in a test file |

# See Also

[`CachedNeighbor`](CachedNeighbor.md) for the edge half of the snapshot.
