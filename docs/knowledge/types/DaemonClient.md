---
type: Class
title: "DaemonClient"
description: "Client for connecting to and querying a running QueryDaemon over its local socket."
resource: code_search/engine/daemon.py#DaemonClient
tags: [daemon, client, ipc]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Client for connecting to and querying a running [`QueryDaemon`](QueryDaemon.md)
over its local socket, used by the CLI to avoid re-loading the index
per-invocation. Defined in [`engine.daemon`](../modules/engine/daemon.md).

# Methods

| Method | Description |
|---|---|
| `__init__(socket_path: Path, timeout: float = 30.0) -> None` | Create a client for the daemon listening on *socket_path*. |
| `is_running(socket_path: Path) -> bool` | Return whether a daemon socket file currently exists at *socket_path*. |
| `request(action: str, params: dict[str, Any] \| None = None) -> dict[str, Any]` | Send one request to the daemon and return its parsed response. |
