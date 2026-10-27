---
type: Function
title: "cmd_status"
description: "Handler for the `status` subcommand: alias for `daemon status`."
resource: code_search/cli/main.py#cmd_status
tags: [cli, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Sets `daemon_action = "status"` and delegates to
[`cmd_daemon`](cmd_daemon.md). Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_status(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments for the `status` subcommand. |

# Returns

The daemon handler's process exit code.
