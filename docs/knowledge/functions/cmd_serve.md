---
type: Function
title: "cmd_serve"
description: "Handler for the `serve` subcommand: starts the MCP stdio server."
resource: src/cli/main.py#cmd_serve
tags: [cli, function, mcp]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `serve` subcommand, constructing an
[`MCPServer`](/types/MCPServer.md) via
[`create_server`](/functions/create_server.md) and running its stdio event
loop. Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_serve(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the `serve` subcommand. |

# Returns

Process exit code (typically does not return until the server stops).
