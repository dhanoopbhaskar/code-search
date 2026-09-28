---
type: Function
title: "cmd_index"
description: "Handler for the `index` subcommand: builds or rebuilds the code index."
resource: src/cli/main.py#cmd_index
tags: [cli, function, indexing]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `index` subcommand, invoking
[`IndexOrchestrator`](/types/IndexOrchestrator.md) to run a full or
incremental index build. Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_index(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the `index` subcommand. |

# Returns

Process exit code.
