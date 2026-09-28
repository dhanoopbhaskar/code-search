---
type: Function
title: "main"
description: "Parse arguments and dispatch to the selected subcommand handler."
resource: src/cli/main.py#main
tags: [cli, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

CLI entry point: parses `sys.argv` via
[`build_parser`](/functions/build_parser.md) and dispatches to the
matching `cmd_*` handler. Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def main(argv: list[str] \| None = None) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `argv` | `list[str] \| None` | Argument vector to parse; defaults to `sys.argv[1:]`. |

# Returns

Process exit code.
