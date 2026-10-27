---
type: Function
title: "cmd_coverage"
description: "Report index gaps for requested paths/scopes, or the whole index."
resource: code_search/cli/main.py#cmd_coverage
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Report index gaps for requested paths/scopes, or the whole index.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_coverage(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `paths`, `scope`, `max_rows`, and `json` are honoured. |

# Returns

`0` when coverage metadata is available, `2` when it is not, or `1` when the index is not initialized.

# Notes

Shares the payload builder with the MCP `check_index_coverage` tool. A
clean result means no gap was recorded, not that every reference resolved.
