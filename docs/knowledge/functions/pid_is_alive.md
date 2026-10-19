---
type: Function
title: "pid_is_alive"
description: "Return whether the daemon pidfile records a live process."
resource: code_search/engine/daemon.py#pid_is_alive
tags: [daemon, function, process]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Reads the pidfile in the context directory and checks the process with
`os.kill(pid, 0)`, which sends no signal. A `PermissionError` counts as alive
(the process belongs to another user); `ProcessLookupError` and other
`OSError`s count as not alive. It is used before removing a socket that does
not answer yet, so a daemon that has bound its socket but is still
initialising is not mistaken for a crashed one. Defined in
[`engine.daemon`](../modules/engine/daemon.md); complements
[`DaemonClient.is_serving`](../types/DaemonClient.md).

# Signature

`def pid_is_alive(context_dir: Path) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory (`.context/`). |

# Returns

`True` when a positive pid is recorded and the process exists.
