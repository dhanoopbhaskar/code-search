---
type: Function
title: "cmd_symbols"
description: "Search symbols by structure: regex name/QN, kind, file, and degree."
resource: code_search/cli/main.py#cmd_symbols
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Search symbols by structure: regex name/QN, kind, file, and degree.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_symbols(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; the structural filters, paging, and `json` are honoured. |

# Returns

`0` when symbols matched, `2` for no match or invalid filters, or `1` when the index is not initialized.

# Notes

Shares the payload builder with the MCP `search_symbols` tool so both
surfaces apply the same filters and ordering.
