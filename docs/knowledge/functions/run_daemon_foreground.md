---
type: Function
title: "run_daemon_foreground"
description: "Run the daemon blocking in the foreground, optionally watching the indexed tree."
resource: code_search/engine/daemon.py#run_daemon_foreground
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Starts and runs a [`QueryDaemon`](../types/QueryDaemon.md) blocking in the
foreground, writing its pidfile and serving requests until stopped; the
pidfile and lifecycle-state file are cleared on exit. Defined in
[`engine.daemon`](../modules/engine/daemon.md); invoked by
[`cmd_daemon_run`](cmd_daemon_run.md) for `daemon run`.

# Signature

`def run_daemon_foreground(context_dir: Path, socket_path: Path, verbose: bool, watch: bool = False) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory to serve. |
| `socket_path` | `Path` | The IPC endpoint the daemon serves on (`AF_UNIX` socket or named pipe). |
| `verbose` | `bool` | Whether to enable verbose logging. |
| `watch` | `bool` | Whether to start a [`LiveIndexUpdater`](../types/LiveIndexUpdater.md) inside the daemon so edited files are re-indexed in the background. Defaults to `False`. |

# Returns

Process exit code (`0` on clean shutdown); blocks until the daemon is stopped.
