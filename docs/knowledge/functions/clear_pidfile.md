---
type: Function
title: "clear_pidfile"
description: "Remove the daemon's pidfile on clean shutdown."
resource: code_search/engine/daemon.py#clear_pidfile
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Removes the daemon's pidfile on clean shutdown. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def clear_pidfile(context_dir: Path) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory (`.context/`). |

# Returns

None.
