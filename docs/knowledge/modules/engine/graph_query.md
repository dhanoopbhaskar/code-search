---
type: Module
title: "engine.graph_query"
description: "Bounded, provenance-labelled graph query, path, explain, impact, change-detection, and aspect-based architecture reporting over symbols and module edges."
resource: code_search/engine/graph_query.py
tags: [graph, query, traversal, provenance]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
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

- `GraphQueryService` — `query`, `shortest_path`, `explain`, `impact`,
  `detect_changes`, `architecture`, and `architecture_report`.
- `GraphNode` / `GraphEdge` / `GraphAnswer` — compact, JSON-serialisable
  traversal results.
- `PathAnswer`, `ExplainAnswer`, `ImpactAnswer`, `ArchitectureReport` —
  command-specific result envelopes; `detect_changes` and `architecture` return
  plain dictionaries shared with the MCP and CLI surfaces.
- `resolve_confidence(tier, resolved)` — maps persisted resolution tiers to
  `EXTRACTED` / `INFERRED` / `AMBIGUOUS` / `UNRESOLVED`.
- `edge_resolution_stats(db)` — per-edge-type resolved/total graph-quality
  metric.
- `display_symbol` / `relative_display` — short symbol labels and
  index-root-relative path rendering shared by every text renderer.
- `render_query_text`, `render_path_text`, `render_explain_text`,
  `render_impact_text`, `render_changes_text`,
  `render_architecture_markdown`, `render_architecture_aspects_text`,
  `compact_json` — deterministic CLI/MCP renderers.

# Traversal Layers

`query`, `shortest_path`, and `impact` walk an in-memory adjacency snapshot from
[`engine.graph_cache`](graph_cache.md) when one is available
(`_cached_path_parents`, `_cached_neighbors`, `_cached_impact_neighbors`) and
fall back to the SQL adjacency (`_sql_path_parents`) otherwise, so the cache is
an optimisation rather than a correctness dependency. `query` accepts
`direction` (`inbound`/`outbound`/`both`), and `impact` accepts `direction`,
`edge_types`, `include_imports`, `fixpoint`, and `seed_filter`, classifying each
impacted node's risk from its fan-in (`_fan_in_counts`, `_impact_risk`).

# Change Detection and Architecture

`detect_changes` resolves changed files from explicit paths or from git
(`base_branch`, else `since`) and reports `scope="files"` (paths only),
`"impact"` (the blast radius), or `"tests"` (test files and test symbols). An
invalid scope/ref combination returns `outcome: invalid_argument`; an empty
change set returns `outcome: no_changes`.

`architecture` answers one *aspect* at a time — `overview`, `structure`,
`dependencies`, `hotspots`, `entry_points`, `clusters`, `cycles`, or `all` —
because the expensive sections (hotspots, clusters) force the full
degree/community pass while the discovery defaults stay cheap. An unsupported
aspect returns `outcome: invalid_argument` with the supported set rather than
being ignored.

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
`query_graph`, `shortest_path`, `explain_symbol`, `get_impact`,
`get_architecture`, and `detect_changes`.
