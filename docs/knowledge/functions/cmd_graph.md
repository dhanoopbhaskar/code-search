---
type: Function
title: "cmd_graph"
description: "Handler for the `graph` subcommand: prints callers/callees of a symbol."
resource: code_search/cli/main.py#cmd_graph
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
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
Paths in human output are rendered relative to the index root.

The command forwards to the resident daemon by default. Output includes
per-edge-type resolution coverage from
[`edge_resolution_stats`](edge_resolution_stats.md); `--explain-unresolved`
lists the anchor symbol's unresolved raw targets when no caller or callee
resolved. An index built with `--no-graph` is reported as
`graph_not_indexed`. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_graph(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `fqn`, `direction`, `depth`, `transitive`, `explain_unresolved`, `json`, and `no_startup_check` are honoured. |

# Returns

A process exit code; `0` on success, `1` when the index is not initialised.
