---
type: Function
title: "daemon_status"
description: "Report {running, warm, socket, pid} for a context directory's daemon."
resource: src/engine/daemon.py#daemon_status
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Reports whether a [`QueryDaemon`](/types/QueryDaemon.md) is running for a
given context directory, along with its warm state, socket path, and
pid. Defined in [`engine.daemon`](/modules/engine/daemon.md).

# Signature

`def daemon_status(context_dir: Path) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory. |

# Returns

A dict with keys `running`, `warm`, `socket`, `pid`.
