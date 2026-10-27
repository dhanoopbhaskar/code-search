---
type: Class
title: "QueryDaemon"
description: "Background daemon keeping the index warm in memory and serving queries over a local socket."
resource: code_search/engine/daemon.py#QueryDaemon
tags: [daemon, server, performance]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Background daemon process that keeps the search index and embedding
model warm in memory, serving queries over a local IPC endpoint to avoid
per-invocation cold-start cost. Dispatches `shutdown`, `ping`, `search`,
`symbol`, `implementations`, `graph`, and `find_related` actions; `shutdown`
stops the daemon from a helper thread so the reply still reaches the caller
(it is what `code-search daemon stop` sends). A forwarded search
waits a bounded `warmup_wait_s` for the model, refuses to serve until the
index status is `ready`, and compacts/relativises results exactly like the
in-process CLI. The socket is bound before components initialise, and a
`code-search.state` file records `starting`/`warming`/`ready`/`failed`/
`stopped`; `ping` reports the state and readiness, while other requests
arriving during startup wait up to `startup_wait_s`. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Methods

| Method | Description |
|---|---|
| `__init__(socket_path: Path, context_dir: Path, verbose: bool = False, watch: bool = False) -> None` | Create a daemon that will serve on *socket_path*; *watch* also starts a [`LiveIndexUpdater`](LiveIndexUpdater.md) so edited files are re-indexed in the background. |
| `start() -> None` | Bind the socket, start component initialisation and model warm-up on a background thread, and serve connections forever. |
| `stop() -> None` | Stop servicing requests, close the socket, remove its path, and record `stopped`. |
| `is_running: bool` (property) | Return whether the daemon's accept loop is active. |
