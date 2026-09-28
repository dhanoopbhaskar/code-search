---
type: Class
title: "DaemonClient"
description: "Client for connecting to and querying a running QueryDaemon over its local socket."
resource: src/engine/daemon.py#DaemonClient
tags: [daemon, client, ipc]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Client for connecting to and querying a running [`QueryDaemon`](/types/QueryDaemon.md)
over its local socket, used by the CLI to avoid re-loading the index
per-invocation. Defined in [`engine.daemon`](/modules/engine/daemon.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, socket_path: Path) -> None` | Initialize the client for a given daemon socket path. |
| `is_available() -> bool` | Return whether a daemon is currently listening on the socket. |
| `send_request(self, request: dict[str, Any]) -> dict[str, Any]` | Send a request to the daemon and return its response. |
