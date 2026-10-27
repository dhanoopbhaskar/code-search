---
type: Class
title: "GraphQueryService"
description: "Offline query, path, explain, impact, change-detection, and aspect-based architecture reporting over the symbol and module graph."
resource: code_search/engine/graph_query.py#GraphQueryService
tags: [graph, query, service]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
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
Walks read the in-memory adjacency snapshot from
[`AdjacencyCache`](AdjacencyCache.md) when one is available and fall back to
the SQL adjacency otherwise, so caching never changes an answer.
Backs the `query`, `path`, `explain`, `affected`, and `map` CLI commands and
the `query_graph`, `shortest_path`, `explain_symbol`, `get_impact`,
`get_architecture`, and `detect_changes` MCP tools. Defined in [`engine.graph_query`](../modules/engine/graph_query.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, symbol_store: SymbolStore, edge_store: EdgeStore, search: Any, settings: Settings \| None = None, module_store: ModuleEdgeStore \| None = None, rationale_store: RationaleStore \| None = None, doc_link_store: DocLinkStore \| None = None, reranker: Any \| None = None) -> None` | Wire the service to the engine components; the optional stores default when omitted. When a *reranker* is supplied, seeds come from the same reranked hits the search surface returns rather than the raw fusion order. |
| `query(question: str, *, depth: int = 2, max_nodes: int = 120, edge_types: set[str] \| None = None, token_budget: int = 1500, seeds: list[str] \| None = None, include_external: bool = False, direction: str = 'both') -> GraphAnswer` | Traverse from hybrid-search (or explicit) seeds; depth is clipped to 4 and nodes to 200; `edge_types` defaults to `CALLS`/`INHERITS` and *direction* selects `inbound`/`outbound`/`both`. Unresolved/external callee leaves are collapsed unless *include_external* is set, and every seed carries a provenance `reason`. |
| `shortest_path(source: str, target: str, *, undirected: bool = False, max_hops: int = 6, edge_types: set[str] \| None = None) -> PathAnswer` | Deterministic BFS between two symbols; ambiguous endpoints are refused with candidates. |
| `explain(symbol: str, *, depth: int = 1, relations: set[str] \| None = None) -> ExplainAnswer` | Ego graph and metadata for a symbol. |
| `impact(changed_paths: list[str], *, depth: int = 3, max_nodes: int = 200, direction: str = 'inbound', edge_types: set[str] \| None = None, include_imports: bool = True, fixpoint: bool = False, seed_filter: str = 'all') -> ImpactAnswer` | BFS over `CALLS`/`INHERITS` from symbols in the changed files, plus importers from reverse `module_edges`; each impacted node carries a risk label derived from its fan-in. |
| `detect_changes(changed_paths: list[str] \| None = None, *, since: str \| None = None, base_branch: str \| None = None, scope: str = 'impact', direction: str = 'inbound', depth: int = 3, fixpoint: bool = False, edge_types: set[str] \| None = None, include_imports: bool = True, seed_filter: str = 'all', max_nodes: int = 200) -> dict[str, Any]` | Resolve changed files from explicit paths or git and report `files`, `impact`, or `tests`; invalid scope/ref returns `invalid_argument`, an empty change set returns `no_changes`. |
| `architecture(*, aspects: set[str] \| None = None, top_n: int = 15, max_communities: int = 10) -> dict[str, Any]` | Answer one architecture aspect (`overview`, `structure`, `dependencies`, `hotspots`, `entry_points`, `clusters`, `cycles`, `all`) without forcing the expensive hotspot/community pass on cheap aspects. |
| `architecture_report(*, top_n: int = 15, max_communities: int = 10, max_edges: int = 20000) -> ArchitectureReport` | God nodes, communities, import cycles, and suggested questions. |

Result types: [`GraphAnswer`](GraphAnswer.md), [`PathAnswer`](PathAnswer.md),
[`ExplainAnswer`](ExplainAnswer.md), [`ImpactAnswer`](ImpactAnswer.md),
[`ArchitectureReport`](ArchitectureReport.md). Backing stores:
[`ModuleEdgeStore`](ModuleEdgeStore.md), [`RationaleStore`](RationaleStore.md),
[`DocLinkStore`](DocLinkStore.md).
