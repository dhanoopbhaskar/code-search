---
type: Function
title: "run_daemon_foreground"
description: "Run the daemon blocking in the foreground."
resource: src/engine/daemon.py#run_daemon_foreground
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Starts and runs a [`QueryDaemon`](/types/QueryDaemon.md) blocking in the
foreground, writing its pidfile and serving requests until stopped.
Defined in [`engine.daemon`](/modules/engine/daemon.md); invoked by
[`cmd_daemon_run`](/functions/cmd_daemon_run.md).

# Signature

`def run_daemon_foreground(context_dir: Path, settings: Settings \| None = None) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory to serve. |
| `settings` | `Settings \| None` | Optional configuration override. |

# Returns

None (blocks until the daemon is stopped).
