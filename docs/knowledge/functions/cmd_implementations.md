---
type: Function
title: "cmd_implementations"
description: "Handler for the `implementations` subcommand: prints subtypes or ancestors of a symbol."
resource: src/cli/main.py#cmd_implementations
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `implementations` subcommand, invoking
[`find_implementations`](/functions/find_implementations.md) or
[`EdgeStore.get_subtypes`](/types/EdgeStore.md)/`get_ancestors` to print
implementations of a symbol. Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_implementations(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments including symbol and lookup kind (subtypes/ancestors). |

# Returns

Process exit code.
