---
type: Module
title: "mcp.server"
description: "MCP stdio server exposing search, symbol, graph, implementations, and find_related tools."
resource: src/mcp/server.py
tags: [mcp, server, api]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/mcp/server.py
    id: source-code
---

# Overview

Model Context Protocol (MCP) stdio server exposing the code-search engine
via five tools: `search` (hybrid keyword + semantic search),
`get_symbol_definition` (FQN lookup), `get_call_neighbors`
(caller/callee traversal), `get_implementations` (interface implementation
lookup), and `find_related` (semantic similarity search). Wraps a
component registry and provides FastMCP tool bindings with auditing,
redaction, and index-freshness signals.

# MCP Tools

| Tool | Purpose |
|---|---|
| `search` | Hybrid keyword + semantic search with reranking and freshness signal |
| `get_symbol_definition` | Resolve a symbol by FQN to its definition, source, and parent |
| `get_call_neighbors` | Traverse `CALLS` edges (callers/callees) up to `max_depth` |
| `get_implementations` | Find static implementers of interface methods/types |
| `find_related` | Find semantically similar chunks via the vector index |

# Key Classes

- [`MCPServer`](/types/MCPServer.md) — serves the code-search engine to MCP clients over stdio.

# Key Functions

- [`create_server`](/functions/create_server.md) — create an `MCPServer` around a component registry.

# Internal Helpers

Private payload builders implement the "one shared rule per tool"
contract so every retrieval surface (CLI, daemon, MCP) agrees:
`_definition_payload`, `_call_neighbors_payload`,
`_implementations_payload`, `_find_related_payload`, plus
`_freshness_signal` and `_serialize` for envelope assembly.
