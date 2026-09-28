---
type: Module
title: "engine.daemon"
description: "Local unix-socket query daemon holding the embedding model and SQLite connections warm across CLI invocations."
resource: src/engine/daemon.py
tags: [engine, daemon, ipc]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/daemon.py
    id: source-code
---

# Overview

Local unix-socket query daemon holding the embedding model and SQLite
connections warm for repeated CLI invocations, avoiding the per-invocation
model load cost (0.5-2s on CPU). Handles JSON requests over a unix socket
(`.context/code-search.sock`) serving search, symbol resolution, graph
traversal, and related-chunk queries with a full audit trail and
index-change detection. Implements both the server
([`QueryDaemon`](/types/QueryDaemon.md)) and a synchronous client
([`DaemonClient`](/types/DaemonClient.md)) used by CLI forwarding.

# Key Classes

- [`QueryDaemon`](/types/QueryDaemon.md) — serves search/symbol/graph/ping over a unix socket, one thread per connection.
- [`DaemonClient`](/types/DaemonClient.md) — synchronous unix-socket client used by CLI forwarding and daemon status.

# Key Functions

- [`default_socket_path`](/functions/default_socket_path.md) — the daemon's socket path convention for a context directory.
- [`daemon_status`](/functions/daemon_status.md) — report `{running, warm, socket, pid}` for a context directory's daemon.
- [`write_pidfile`](/functions/write_pidfile.md), [`clear_pidfile`](/functions/clear_pidfile.md) — daemon pidfile lifecycle.
- [`run_daemon_foreground`](/functions/run_daemon_foreground.md) — run the daemon blocking in the foreground.

# Internal Helpers

`_daemon_freshness` mirrors the shared freshness signal so direct and
daemon-forwarded CLI output agree; `_pidfile_path`/`_read_pidfile` are
pidfile path/read helpers.
