---
type: Function
title: "cmd_daemon"
description: "Handler for the `daemon` subcommand: start/stop/status control of the QueryDaemon."
resource: src/cli/main.py#cmd_daemon
tags: [cli, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `daemon` subcommand, dispatching start/stop/status actions
against [`QueryDaemon`](/types/QueryDaemon.md) via
[`daemon_status`](/functions/daemon_status.md) and pidfile helpers.
Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_daemon(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments including the daemon action (start/stop/status). |

# Returns

Process exit code.
