---
type: Function
title: "create_server"
description: "Create an MCPServer around a component registry."
resource: src/mcp/server.py#create_server
tags: [mcp, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/mcp/server.py
    id: source-code
---

# Overview

Factory constructing an [`MCPServer`](/types/MCPServer.md) instance,
wiring up its search/graph/symbol/embedding components. Defined in
[`mcp.server`](/modules/mcp/server.md).

# Signature

`def create_server(index_path: Path, settings: Settings \| None = None) -> MCPServer`

# Parameters

| Name | Type | Description |
|---|---|---|
| `index_path` | `Path` | Path to the built index directory. |
| `settings` | `Settings \| None` | Optional configuration override. |

# Returns

A ready-to-run [`MCPServer`](/types/MCPServer.md) instance.
