---
type: Function
title: "default_socket_path"
description: "The daemon's socket path convention for a context directory."
resource: src/engine/daemon.py#default_socket_path
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Returns the daemon's conventional Unix socket path for a given context
(index) directory. Defined in
[`engine.daemon`](/modules/engine/daemon.md).

# Signature

`def default_socket_path(context_dir: Path) -> Path`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The index/context directory. |

# Returns

The conventional socket path for that context.
