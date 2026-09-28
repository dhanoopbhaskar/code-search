---
type: Module
title: "src.mcp"
description: "Model Context Protocol (MCP) server package for code-search."
resource: src/mcp/__init__.py
tags: [mcp, package]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/mcp/__init__.py
    id: source-code
---

# Overview

Model Context Protocol (MCP) server for code-search. Exposes the engine to
MCP clients over stdio via the [`server`](/modules/mcp/server.md) module,
implementing `search`, `get_symbol_definition`, `get_call_neighbors`,
`get_implementations`, and `find_related` tools.
