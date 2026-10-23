---
type: Function
title: "write_state"
description: "Record the daemon lifecycle state (`starting`/`warming`/`ready`)."
resource: code_search/engine/daemon.py#write_state
tags: [daemon, function, lifecycle]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Writes the daemon lifecycle state to `code-search.state` in the context
directory so a waiting client can distinguish a slow start from a crashed
daemon. I/O failures are suppressed. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def write_state(context_dir: Path, state: str) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory. |
| `state` | `str` | One of `starting`, `warming`, `ready`, `failed`, or `stopped`. |

# Returns

None.
