---
type: Function
title: "edge_resolution_stats"
description: "Per-edge-type resolved/unresolved counts used as a graph-quality metric."
resource: code_search/engine/graph_query.py#edge_resolution_stats
tags: [graph, function, metrics]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Aggregates `graph_edges` by `edge_type` and reports how many edges resolved
to a symbol. A healthy index keeps a non-zero resolved ratio for every
produced edge type. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def edge_resolution_stats(db: GraphDatabase) -> dict[str, dict[str, int]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | [`GraphDatabase`](../types/GraphDatabase.md) | Graph database to read. |

# Returns

A mapping from edge type to `{total, resolved, unresolved, ratio}`. `ratio` is
the resolved share in permille (`round(1000 * resolved / total)`, `0` when
there are no edges), not a fraction.
