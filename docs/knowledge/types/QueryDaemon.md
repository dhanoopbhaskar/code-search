---
type: Class
title: "QueryDaemon"
description: "Background daemon keeping the index warm in memory and serving queries over a local socket."
resource: src/engine/daemon.py#QueryDaemon
tags: [daemon, server, performance]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Background daemon process that keeps the search index and embedding
model warm in memory, serving queries over a local Unix socket to avoid
per-invocation cold-start cost. Defined in
[`engine.daemon`](/modules/engine/daemon.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, index_path: Path, socket_path: Path, settings: Settings \| None = None) -> None` | Initialize the daemon over an index and socket path. |
| `start() -> None` | Load the index/model and begin accepting connections. |
| `stop() -> None` | Gracefully shut down the daemon and close the socket. |
| `handle_request(self, request: dict[str, Any]) -> dict[str, Any]` | Dispatch a single incoming request to the appropriate handler. |
| `is_running() -> bool` | Return whether the daemon's socket is currently accepting connections. |
