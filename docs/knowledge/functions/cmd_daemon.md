---
type: Function
title: "cmd_daemon"
description: "Handler for the `daemon` subcommand: start, stop, status, or wait on the local QueryDaemon."
resource: code_search/cli/main.py#cmd_daemon
tags: [cli, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `daemon` subcommand, dispatching its `start`, `stop`, `status`, and
`wait` actions against [`QueryDaemon`](../types/QueryDaemon.md) through
[`daemon_status`](daemon_status.md),
[`DaemonClient`](../types/DaemonClient.md), [`pid_is_alive`](pid_is_alive.md),
[`prepare_socket_path`](prepare_socket_path.md), and the pidfile helpers.
Defined in [`cli.main`](../modules/cli/main.md). The `run` action is handled by
[`cmd_daemon_run`](cmd_daemon_run.md).

# Signature

`def cmd_daemon(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `daemon_action` (`start`/`stop`/`status`/`wait`), `port`, and `watch` (start only) are honoured, plus the global options. |

# Actions

| Action | Behaviour |
|---|---|
| `status` | Report `running (pid=…, socket=…, state=…)` or `not running (state=…)` from [`daemon_status`](daemon_status.md); exit `0` either way. |
| `wait` | Poll [`daemon_status`](daemon_status.md) every 100 ms until the daemon is both running and warm, then print `ready`. `--timeout` bounds the wait (default 30 s); on expiry it prints `timed out waiting for a warm daemon` to stderr and exits `1`. |
| `stop` | Ask the daemon to shut itself down over IPC so its own cleanup (state file, socket unlink, log flush) runs on every platform, then fall back to `SIGTERM` if the process outlives the 5 s grace period, retry the socket unlink, and clear the pidfile. Prints `not running` and exits `0` when nothing is running. |
| `start` | Return early when a daemon is already serving. A live pidfile whose daemon is still initialising is waited on for up to `startup_wait_s` instead of spawning a second process. Otherwise prepare the endpoint, spawn `daemon run` detached with its output appended to `code-search-daemon.log`, record the pidfile, and print `started (pid=…, socket=…)`. `--watch` is forwarded so the daemon re-indexes edited files. |

# Returns

Process exit code: `0` when the action succeeded — including the no-op cases
where the daemon was already running or already stopped — and `1` when `wait`
timed out, `start` found a daemon stuck in startup, or `start` failed.
