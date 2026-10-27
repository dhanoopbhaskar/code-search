---
type: Function
title: "cmd_map"
description: "Handler for the `map` subcommand: generates a deterministic architecture report."
resource: code_search/cli/main.py#cmd_map
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `map` subcommand: calls
[`GraphQueryService.architecture_report`](../types/GraphQueryService.md) and
renders the [`ArchitectureReport`](../types/ArchitectureReport.md) with
[`render_architecture_markdown`](render_architecture_markdown.md), printing it
or writing it to `--output`; `--json` prints the structured report instead. The
call is audited as `map`.

With `--aspects`, the command instead asks
[`GraphQueryService.architecture`](../types/GraphQueryService.md) for the bounded
aspect payload the MCP `get_architecture` tool returns, renders it with
[`render_architecture_aspects_text`](render_architecture_aspects_text.md) (or
JSON), and is audited as `get_architecture`. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_map(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `top` (default 15), `max_communities` (default 10), `aspects` (comma-separated bounded sections such as `overview`, `hotspots`, `cycles`, or `all`), `output`, `json`, and the global options are honoured. |

# Returns

`0` on success, `1` when the index or the graph is not initialised, and `2`
when `--aspects` names an unsupported section.
