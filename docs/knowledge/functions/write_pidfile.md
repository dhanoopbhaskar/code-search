---
type: Function
title: "write_pidfile"
description: "Write the daemon's pidfile for lifecycle tracking."
resource: src/engine/daemon.py#write_pidfile
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Writes the daemon's pidfile so `daemon_status`/`cmd_daemon` can detect and
stop the running process. Defined in
[`engine.daemon`](/modules/engine/daemon.md).

# Signature

`def write_pidfile(context_dir: Path, pid: int) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory. |
| `pid` | `int` | The daemon process id to record. |

# Returns

None.
