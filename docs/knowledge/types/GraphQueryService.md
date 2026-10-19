---
type: Class
title: "GraphQueryService"
description: "Offline query, path, explain, impact, and architecture reporting over the symbol and module graph."
resource: code_search/engine/graph_query.py#GraphQueryService
tags: [graph, query, service]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Walks resolved `graph_edges` (and optional `module_edges`) with bounded,
deterministic BFS. Seeds come from [`HybridSearch`](HybridSearch.md);
endpoints resolve through the shared ambiguity policy of
[`SymbolStore`](SymbolStore.md). It uses no network, LLM, or graph library.
Backs the `query`, `path`, `explain`, `affected`, and `map` CLI commands and
the `query_graph`, `shortest_path`, `explain_symbol`, and `get_impact` MCP
tools. Defined in [`engine.graph_query`](../modules/engine/graph_query.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, symbol_store: SymbolStore, edge_store: EdgeStore, search: Any, settings: Settings \| None = None, module_store: ModuleEdgeStore \| None = None, rationale_store: RationaleStore \| None = None, doc_link_store: DocLinkStore \| None = None) -> None` | Wire the service to the engine components; the optional stores default when omitted. |
| `query(question: str, *, depth: int = 2, max_nodes: int = 120, edge_types: set[str] \| None = None, token_budget: int = 1500, seeds: list[str] \| None = None) -> GraphAnswer` | Traverse from hybrid-search (or explicit) seeds; depth is clipped to 4 and nodes to 200; `edge_types` defaults to `CALLS`/`INHERITS`. |
| `shortest_path(source: str, target: str, *, undirected: bool = False, max_hops: int = 6, edge_types: set[str] \| None = None) -> PathAnswer` | Deterministic BFS between two symbols; ambiguous endpoints are refused with candidates. |
| `explain(symbol: str, *, depth: int = 1, relations: set[str] \| None = None) -> ExplainAnswer` | Ego graph and metadata for a symbol. |
| `impact(changed_paths: list[str], *, depth: int = 3, max_nodes: int = 200) -> ImpactAnswer` | Reverse BFS over `CALLS`/`INHERITS` from symbols in the changed files, plus importers from reverse `module_edges`. |
| `architecture_report(*, top_n: int = 15, max_communities: int = 10, max_edges: int = 20000) -> ArchitectureReport` | God nodes, communities, import cycles, and suggested questions. |

Result types: [`GraphAnswer`](GraphAnswer.md), [`PathAnswer`](PathAnswer.md),
[`ExplainAnswer`](ExplainAnswer.md), [`ImpactAnswer`](ImpactAnswer.md),
[`ArchitectureReport`](ArchitectureReport.md). Backing stores:
[`ModuleEdgeStore`](ModuleEdgeStore.md), [`RationaleStore`](RationaleStore.md),
[`DocLinkStore`](DocLinkStore.md).
