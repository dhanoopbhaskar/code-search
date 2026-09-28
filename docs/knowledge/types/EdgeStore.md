---
type: Class
title: "EdgeStore"
description: "High-level CRUD for call-graph edges and traversal queries."
resource: src/engine/graph.py#EdgeStore
tags: [graph, edges, traversal]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/graph.py
    id: source-code
---

# Overview

High-level CRUD for call-graph edges and traversal queries. Defined in
[`engine.graph`](/modules/engine/graph.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, db: GraphDatabase, settings: Settings \| None = None) -> None` | Initialize the edge store over a graph database. |
| `insert_edge(self, source_symbol_id, target_symbol_id, edge_type, source_range=None, target_range=None, resolution_tier=None) -> int \| None` | Insert a single directed edge; skips self-loops. |
| `insert_edges_batch(self, edges: list[dict[str, Any]]) -> None` | Insert many edges at once. |
| `run_edge_validation_sweep() -> dict[str, int]` | Post-index validation sweep; delete spurious edges; return `{deleted, kept_recursive}`. |
| `resolve_symbol_definition(self, fqn: str) -> tuple[dict[str, Any] \| None, list[dict[str, Any]]]` | Resolve *fqn* to `(symbol, candidates)` with source code populated. |
| `get_symbol_definition(self, fqn: str) -> dict[str, Any] \| None` | Look up a symbol by FQN, returning its definition + source + parent info. |
| `get_call_graph(self, symbol_id: int, direction: str = "both", max_depth: int = 1) -> dict[str, list[dict[str, Any]]]` | Traverse callers and/or callees via recursive CTE; returns `{callers, callees}`. |
| `get_subtypes(self, symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]` | Return types that inherit from *symbol_id*, with minimum depth. |
| `get_ancestors(self, symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]` | Return the class ancestors of *symbol_id*, nearest base first. |
