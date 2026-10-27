---
type: Function
title: "endpoint_exists"
description: "Return whether a daemon endpoint is present."
resource: code_search/engine/daemon.py#endpoint_exists
tags: [engine, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Return whether a daemon endpoint is present.

Defined in [`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def endpoint_exists(socket_path: Path) -> bool`

# Parameters

| Name | Description |
|---|---|
| `socket_path` | The IPC endpoint to inspect. |

# Returns

`True` when the POSIX socket file exists or a named-pipe listener is reachable.
