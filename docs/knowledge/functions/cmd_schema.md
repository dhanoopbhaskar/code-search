---
type: Function
title: "cmd_schema"
description: "Describe the graph schema an agent is about to query."
resource: code_search/cli/main.py#cmd_schema
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Describe the graph schema an agent is about to query.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_schema(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `diagnostics`, `limit`, `offset`, and `json` are honoured. |

# Returns

`0` on success, `1` when the index is not initialized, or `2` when the graph was not indexed.

# Notes

Reports stored node labels, supported and emitted edge types, resolution
tiers, symbol totals, coverage gaps, and the index generation. Shares the
payload builder with the MCP `get_graph_schema` tool.
