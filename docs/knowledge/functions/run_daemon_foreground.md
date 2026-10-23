---
type: Function
title: "run_daemon_foreground"
description: "Run the daemon blocking in the foreground."
resource: code_search/engine/daemon.py#run_daemon_foreground
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Starts and runs a [`QueryDaemon`](../types/QueryDaemon.md) blocking in the
foreground, writing its pidfile and serving requests until stopped.
Defined in [`engine.daemon`](../modules/engine/daemon.md); invoked by
[`cmd_daemon_run`](cmd_daemon_run.md).

# Signature

`def run_daemon_foreground(context_dir: Path, socket_path: Path, verbose: bool) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory to serve. |
| `socket_path` | `Path` | The AF_UNIX socket path the daemon serves on. |
| `verbose` | `bool` | Whether to enable verbose logging. |

# Returns

Process exit code (`0` on clean shutdown); blocks until the daemon is stopped.
