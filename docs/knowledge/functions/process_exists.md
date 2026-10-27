---
type: Function
title: "process_exists"
description: "Return whether pid names a live process without signalling it."
resource: code_search/engine/daemon.py#process_exists
tags: [engine, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Return whether `pid` names a live process without signalling it.

Defined in [`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def process_exists(pid: int) -> bool`

# Parameters

| Name | Description |
|---|---|
| `pid` | The process id to probe. |

# Returns

`True` when the process exists (including when it belongs to another user), `False` when it does not.

# Notes

`os.kill(pid, 0)` is a harmless existence probe on POSIX, but on Windows
every signal other than the two console events unconditionally terminates
the target, so the existence check must go through `OpenProcess` there.
