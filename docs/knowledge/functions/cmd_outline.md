---
type: Function
title: "cmd_outline"
description: "List one file's declarations in source order."
resource: code_search/cli/main.py#cmd_outline
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

List one file's declarations in source order.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_outline(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `file`, `kind`, `limit`, `offset`, `include_docstring`, and `json` are honoured. |

# Returns

`0` when the file is indexed, `2` when it is not, or `1` when the index is not initialized.

# Notes

Shares the payload builder with the MCP `get_file_outline` tool so a file
outline is identical across surfaces.
