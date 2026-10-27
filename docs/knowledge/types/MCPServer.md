---
type: Class
title: "MCPServer"
description: "FastMCP server exposing search and code-navigation tools over stdio."
resource: code_search/mcp/server.py#MCPServer
tags: [mcp, server, stdio]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/mcp/server.py
    id: source-code
---

# Overview

FastMCP server exposing search, symbol-definition, call-neighbor,
implementation, `find_related`, graph-query, shortest-path, explain, and
impact tools over stdio for AI agent consumption. The `find_related` tool
delegates ranking to
[`engine.find_related`](../modules/engine/find_related.md) and adds only
transport concerns. Defined in [`mcp.server`](../modules/mcp/server.md); wraps
[`HybridSearch`](HybridSearch.md), [`EdgeStore`](EdgeStore.md),
and [`SymbolStore`](SymbolStore.md).

# Methods

| Method | Description |
|---|---|
| `__init__(components: dict[str, Any]) -> None` | Create an MCP server wired to the shared component registry. |
| `register_tool(name: str, handler: object) -> None` | Register a tool *handler* under *name*. |
| `build_fastmcp() -> Any` | Build the FastMCP server with the nine MCP tools registered. |
| `run(transport: str = 'stdio') -> None` | Serve the MCP tools over the requested transport. |
