---
type: Function
title: "cmd_symbol"
description: "Handler for the `symbol` subcommand: resolves and prints a symbol's definition."
resource: src/cli/main.py#cmd_symbol
tags: [cli, function, symbols]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `symbol` subcommand, invoking
[`SymbolStore.resolve_name`](/types/SymbolStore.md) to resolve and print a
symbol's definition. Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_symbol(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments including the symbol name/FQN query. |

# Returns

Process exit code.
