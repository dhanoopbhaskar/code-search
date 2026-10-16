---
type: Function
title: "write_pidfile"
description: "Write the daemon's pidfile for lifecycle tracking."
resource: code_search/engine/daemon.py#write_pidfile
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Writes the daemon's pidfile so `daemon_status`/`cmd_daemon` can detect and
stop the running process. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def write_pidfile(context_dir: Path) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory (`.context/`). |

# Returns

None.
