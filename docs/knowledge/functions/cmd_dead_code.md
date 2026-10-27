---
type: Function
title: "cmd_dead_code"
description: "Report callables with no proven production reference."
resource: code_search/cli/main.py#cmd_dead_code
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Report callables with no proven production reference.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_dead_code(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; kinds, exclusions, paging, and `json` are honoured. |

# Returns

`0` when the query ran, `2` for invalid filters, or `1` when the index is not initialized.

# Notes

Shares the payload builder with the MCP `find_dead_code` tool. The
command reports candidates and their limitations; it never recommends
deleting code.
