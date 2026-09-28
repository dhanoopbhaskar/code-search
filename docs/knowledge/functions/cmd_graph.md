---
type: Function
title: "cmd_graph"
description: "Handler for the `graph` subcommand: prints callers/callees of a symbol."
resource: src/cli/main.py#cmd_graph
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `graph` subcommand, invoking
[`EdgeStore.get_call_graph`](/types/EdgeStore.md) to print callers and/or
callees of a symbol. Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_graph(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments including symbol, direction, and depth. |

# Returns

Process exit code.
