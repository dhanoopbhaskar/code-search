---
type: Class
title: "MCPServer"
description: "FastMCP server exposing search and code-navigation tools over stdio."
resource: src/mcp/server.py#MCPServer
tags: [mcp, server, stdio]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/mcp/server.py
    id: source-code
---

# Overview

FastMCP server exposing search, symbol-definition, call-neighbor,
implementation, and `find_related` tools over stdio for AI agent
consumption. Defined in [`mcp.server`](/modules/mcp/server.md); wraps
[`HybridSearch`](/types/HybridSearch.md), [`EdgeStore`](/types/EdgeStore.md),
and [`SymbolStore`](/types/SymbolStore.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, index_path: Path, settings: Settings \| None = None) -> None` | Load index components and register MCP tools. |
| `search(self, query: str, top_k: int = 10, ...) -> dict[str, Any]` | MCP tool: run hybrid search and return a response envelope. |
| `get_symbol_definition(self, fqn: str) -> dict[str, Any]` | MCP tool: resolve and return a symbol's definition + source. |
| `get_call_neighbors(self, fqn: str, direction: str = "both", max_depth: int = 1) -> dict[str, Any]` | MCP tool: return callers/callees of a symbol. |
| `get_implementations(self, fqn: str, kind: str = "subtypes") -> dict[str, Any]` | MCP tool: return subtypes or ancestors of a symbol. |
| `find_related(self, file_path: str, ...) -> dict[str, Any]` | MCP tool: return chunks related to a given file. |
| `run() -> None` | Start the FastMCP stdio event loop. |
