---
type: Function
title: "cmd_graph"
description: "Handler for the `graph` subcommand: prints callers/callees of a symbol."
resource: code_search/cli/main.py#cmd_graph
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `graph` subcommand, invoking
[`EdgeStore.get_call_graph`](../types/EdgeStore.md) to print callers and/or
callees of a symbol; `--direction implements` instead reports static
implementations via [`find_implementations`](find_implementations.md).
Paths in human output are rendered relative to the index root. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_graph(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `fqn`, `direction`, `depth`, `transitive`, and `json` are honoured. |

# Returns

A process exit code; `0` on success, `1` when the index is not initialised.
