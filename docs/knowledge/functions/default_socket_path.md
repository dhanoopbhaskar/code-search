---
type: Function
title: "default_socket_path"
description: "The daemon's socket path convention for a context directory."
resource: code_search/engine/daemon.py#default_socket_path
tags: [daemon, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Returns the daemon's IPC endpoint for a given context (index) directory. On
Windows CPython does not expose `AF_UNIX`, so the endpoint is a deterministic
named pipe (`\\.\pipe\code-search-<user>-<digest>`) with no filesystem
entry. On Linux/macOS it prefers the conventional
`context_dir / "code-search.sock"`; when that path exceeds the `AF_UNIX` limit
(`_MAX_UNIX_SOCKET_PATH` = 103 encoded bytes on macOS, 107 elsewhere), it falls
back to a deterministic hashed name (`code-search-<user>-<digest>.sock`) under
`$XDG_RUNTIME_DIR` when that directory is writable, otherwise the system temp
directory, so a deep checkout path cannot stop the daemon from binding.
Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def default_socket_path(context_dir: Path) -> Path`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory (`.context/`). |

# Returns

The endpoint to bind; identical for every process resolving the same
*context_dir*.
