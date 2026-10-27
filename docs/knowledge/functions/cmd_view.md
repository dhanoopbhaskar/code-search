---
type: Function
title: "cmd_view"
description: "Read a symbol or file with a compact outline/body contract."
resource: code_search/cli/main.py#cmd_view
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Read a symbol or file with a compact outline/body contract.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_view(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `target`, `outline`/`body`, `max_lines`, `budget`, and `json` are honoured. |

# Returns

`0` when resolved, `2` when nothing matched or the file is not indexed, `3` when the symbol reference is ambiguous, or `1` when the index is not initialized.

# Notes

Containers longer than 200 lines default to an outline with
`source_omitted: true`; `--body` forces the source and `--outline`
forces the member list. `--max-lines` and `--budget` bound the returned
text so callers can ask for a cheap read instead of a whole class body.
