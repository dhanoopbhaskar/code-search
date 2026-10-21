---
type: Module
title: "engine.graph_query"
description: "Bounded, provenance-labelled graph query, path, explain, impact, and architecture reporting over symbols and module edges."
resource: code_search/engine/graph_query.py
tags: [graph, query, traversal, provenance]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Graph traversal and explanation layer built on the existing SQLite symbol
graph, hybrid-search seed ranker, and additive `module_edges` table. It never
calls an LLM or the network and adds no graph-library dependency.

# Key Entities

- `GraphQueryService` — `query`, `shortest_path`, `explain`, `impact`, and
  `architecture_report`.
- `GraphNode` / `GraphEdge` / `GraphAnswer` — compact, JSON-serialisable
  traversal results.
- `PathAnswer`, `ExplainAnswer`, `ImpactAnswer`, `ArchitectureReport` —
  command-specific result envelopes.
- `resolve_confidence(tier, resolved)` — maps persisted resolution tiers to
  `EXTRACTED` / `INFERRED` / `AMBIGUOUS` / `UNRESOLVED`.
- `edge_resolution_stats(db)` — per-edge-type resolved/total graph-quality
  metric.
- `display_symbol` / `relative_display` — short symbol labels and
  index-root-relative path rendering shared by every text renderer.
- `render_query_text`, `render_path_text`, `render_explain_text`,
  `render_impact_text`, `render_architecture_markdown`, `compact_json` —
  deterministic CLI/MCP renderers.

# Behaviour

Seeds come from the same reranked hits the search surface returns (with an
identifier fallback when the ranker returns nothing), and every seed records a
provenance `reason` such as `hybrid search hit #2 (score 0.812)`. Traversal is
bounded by depth, node count, per-node fanout, and a token budget. Symbol
results follow the stored edge direction; incoming edges are labelled
`(backwards)`. Containment (`CONTAINS`) is synthesised from
`symbols.parent_symbol_id` so a type seed can reach its members. Unresolved or
external callee leaves are collapsed unless `include_external` is set, with the
collapsed count reported in `stats["collapsed_externals"]`.

# Surfaces

`code-search query`, `path`, `explain`, `affected`, and `map`; MCP tools
`query_graph`, `shortest_path`, `explain_symbol`, and `get_impact`.
