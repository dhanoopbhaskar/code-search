---
type: Class
title: "QueryDaemon"
description: "Background daemon keeping the index warm in memory and serving queries over a local socket."
resource: code_search/engine/daemon.py#QueryDaemon
tags: [daemon, server, performance]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Background daemon process that keeps the search index and embedding
model warm in memory, serving queries over a local Unix socket to avoid
per-invocation cold-start cost. Dispatches `ping`, `search`, `symbol`,
`implementations`, `graph`, and `find_related` actions. A forwarded search
waits a bounded `warmup_wait_s` for the model, refuses to serve until the
index status is `ready`, and compacts/relativises results exactly like the
in-process CLI. Defined in [`engine.daemon`](../modules/engine/daemon.md).

# Methods

| Method | Description |
|---|---|
| `__init__(socket_path: Path, context_dir: Path, verbose: bool = False) -> None` | Create a daemon that will serve on *socket_path*. |
| `start() -> None` | Initialise components, bind the socket, and serve connections forever. |
| `stop() -> None` | Stop servicing requests, close the socket, and remove its path. |
| `is_running: bool` (property) | Return whether the daemon's accept loop is active. |
