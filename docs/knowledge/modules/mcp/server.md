---
type: Module
title: "mcp.server"
description: "MCP stdio server exposing search, ask, definition, call graph, graph discovery, Cypher, architecture, change, and impact tools with profile/budget output shaping."
resource: code_search/mcp/server.py
tags: [mcp, server, api]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/mcp/server.py
    id: source-code
---

# Overview

Model Context Protocol (MCP) stdio server exposing the code-search engine as 19
tools. Each tool is a thin binding over a shared engine payload builder
(`_definition_payload`, `_call_neighbors_payload`, `_implementations_payload`,
`_find_related_payload`, or a function in
[`engine.graph_surface`](../engine/graph_surface.md) /
[`engine.graph_query`](../engine/graph_query.md) /
[`engine.cypher`](../engine/cypher.md) /
[`engine.ask`](../engine/ask.md)), so the MCP, CLI, and daemon surfaces cannot
drift. Every response carries an index-freshness signal, passes through the
redactor, and is recorded in the audit trail. `find_related` delegates anchor
resolution and neighbour ranking to
[`engine.find_related`](../engine/find_related.md), adding only transport
concerns.

# MCP Tools

| Tool | Purpose |
|---|---|
| `search` | Hybrid keyword + semantic search with reranking and freshness signal |
| `get_symbol_definition` | Resolve a symbol by FQN to its definition, source, and parent |
| `get_call_neighbors` | Traverse `CALLS` edges (callers/callees) up to `max_depth`, with paging |
| `get_implementations` | Find static implementers of interface methods/types |
| `find_related` | Find semantically similar chunks via the vector index |
| `get_graph_schema` | Labels, edge types, tiers, coverage, and generation |
| `get_file_outline` | Declarations of one file in source order |
| `check_index_coverage` | Distinguish "not found" from "not indexed" |
| `search_symbols` | Structural search by regex, kind, file, and degree |
| `find_dead_code` | Callables with no proven production reference |
| `get_architecture` | Bounded architecture aspects |
| `query_graph` | Answer a multi-hop question by bounded graph traversal |
| `shortest_path` | Shortest directed/undirected path between symbols |
| `explain_symbol` | Symbol metadata, relations, rationale, and linked docs |
| `get_impact` | Reverse-traverse changed files to impacted symbols |
| `detect_changes` | Resolve git or explicit changes into files, impact, or tests |
| `cypher_query` | Read-only Cypher subset for multi-hop and aggregate questions |
| `ask` | Route one question to the right surface and return one answer |
| `doctor` | Index, model, daemon, and graph health in one call |

# Output Shaping

Every tool returns through `_finish`, which applies a `profile` and an optional
`max_output_tokens` budget before serializing:

- `compact` (default) and `full` leave the payload as the engine shaped it.
- `outline` empties `content`/`source_code` in every row and sets
  `source_omitted`, so a caller can inspect structure without paying for bodies.
- The budget trims the largest list first (front rows — the relevant ones —
  survive), sets `truncated`, and finally drops `explanation`/`coverage`/`paging`
  before declaring `budget_exceeded`.

# Key Classes

- [`MCPServer`](../../types/MCPServer.md) — serves the code-search engine to MCP clients over stdio.

# Key Functions

- [`create_server`](../../functions/create_server.md) — create an `MCPServer` around a component registry.

# Internal Helpers

`_freshness_signal` renders the shared freshness signal (with a truthful
metadata fallback rather than a guessed "fresh"), `_serialize` wraps a payload
with it, and `_payload_chars`/`_fit_output_budget`/`_apply_profile`/`_finish`
implement the output contract described above.
`_call_neighbors_payload` accepts an optional database handle to attach
`coverage` and `limit`/`offset` paging.

