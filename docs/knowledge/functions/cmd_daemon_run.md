---
type: Function
title: "cmd_daemon_run"
description: "Handler that runs the daemon blocking in the foreground (used internally by `cmd_daemon start`)."
resource: src/cli/main.py#cmd_daemon_run
tags: [cli, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Runs the [`QueryDaemon`](/types/QueryDaemon.md) blocking in the
foreground via
[`run_daemon_foreground`](/functions/run_daemon_foreground.md); typically
invoked as a detached subprocess by `cmd_daemon`. Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_daemon_run(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the internal daemon-run entry point. |

# Returns

Process exit code (blocks until the daemon stops).
