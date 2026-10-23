---
type: Function
title: "cmd_start"
description: "Handler for the `start` subcommand: alias for `daemon start`."
resource: code_search/cli/main.py#cmd_start
tags: [cli, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Sets `daemon_action = "start"` and delegates to
[`cmd_daemon`](cmd_daemon.md). Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_start(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments for the `start` subcommand. |

# Returns

The daemon handler's process exit code.
