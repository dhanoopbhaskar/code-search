---
type: Function
title: "cmd_path"
description: "Handler for the `path` subcommand: prints the shortest graph path between two symbols."
resource: code_search/cli/main.py#cmd_path
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `path` subcommand: calls
[`GraphQueryService.shortest_path`](../types/GraphQueryService.md) and prints
the hop chain with [`render_path_text`](render_path_text.md), or JSON under
`--json`. Each call is audited as `shortest_path`. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_path(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `source`, `target`, `undirected`, `max_hops` (default 6), `edge_types` (default `CALLS,INHERITS`), `json`, and the global options are honoured. |

# Returns

`0` when the outcome is `resolved` or `trivial`, `2` for any other outcome
(for example an ambiguous or unreachable endpoint), `1` when the index is
not initialised.
