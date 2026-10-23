---
type: Function
title: "cmd_implementations"
description: "Handler for the `implementations` subcommand: prints subtypes or ancestors of a symbol."
resource: code_search/cli/main.py#cmd_implementations
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `implementations` subcommand, invoking
[`find_implementations`](find_implementations.md) to print
implementations of a symbol. It forwards to the resident daemon by default and
skips the vector sidecar when resolving in process. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_implementations(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `fqn` and `json` are honoured. |

# Returns

A process exit code; `0` on success, `1` when the index is not initialised.
