---
type: Class
title: "EdgeStore"
description: "High-level CRUD for call-graph edges and traversal queries."
resource: code_search/engine/graph.py#EdgeStore
tags: [graph, edges, traversal]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

High-level CRUD for call-graph edges and traversal queries. Defined in
[`engine.graph`](../modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, settings: Settings \| None = None) -> None` | Initialize the edge store over a graph database. |
| `insert_edge(source_symbol_id: int, target_symbol_id: int, edge_type: str, source_range: str \| None = None, target_range: str \| None = None, resolution_tier: str \| None = None) -> int \| None` | Insert a single directed edge between two symbols. |
| `insert_edges_batch(edges: list[dict[str, Any]], conn: sqlite3.Connection \| None = None) -> None` | Insert many edges at once, guarding against spurious self-edges; reuse *conn* when given, otherwise open and commit a transaction. |
| `run_edge_validation_sweep() -> dict[str, int]` | Post-index edge validation sweep. |
| `resolve_symbol_definition(fqn: str) -> tuple[dict[str, Any] \| None, list[dict[str, Any]]]` | Resolve *fqn* to `(symbol, candidates)` with source code populated. |
| `get_symbol_definition(fqn: str) -> dict[str, Any] \| None` | Look up a symbol by FQN, returning its definition + source code + parent info. |
| `get_call_graph(symbol_id: int, direction: str = 'both', max_depth: int = 1) -> dict[str, list[dict[str, Any]]]` | Traverse callers and/or callees via recursive CTE, clipped to *max_depth*. |
| `get_subtypes(symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]` | Return types that inherit from *symbol_id*, with minimum depth. |
| `get_ancestors(symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]` | Return the class ancestors of *symbol_id*, nearest base first. |
| `get_inheritance_targets(symbol_id: int) -> list[dict[str, Any]]` | Return the declared `INHERITS` targets of *symbol_id* as `{name, fqn, resolved}`, reading `target_raw` for unresolved edges. |
