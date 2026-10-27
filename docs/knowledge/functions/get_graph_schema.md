---
type: Function
title: "get_graph_schema"
description: "Return a bounded description of the graph an agent is about to query."
resource: code_search/engine/graph_surface.py#get_graph_schema
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Return a bounded description of the graph an agent is about to query.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def get_graph_schema(db: GraphDatabase, *, diagnostics: bool = False, node_limit: int = 100, offset: int = 0) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `diagnostics` | When true, add per-edge property-key diagnostics sampled from stored edge properties (capped at 1,000 rows). |
| `node_limit` | Maximum node labels to return (clipped to 500). |
| `offset` | Zero-based offset into the sorted node-label list. |

# Returns

A JSON-serialisable dict with generation, supported and stored labels, edge-type counts, resolution tiers, symbol totals, and coverage counts.
