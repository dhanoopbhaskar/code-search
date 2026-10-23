---
type: Module
title: "engine.daemon"
description: "Local AF_UNIX socket query daemon holding the embedding model and SQLite connections warm across CLI invocations."
resource: code_search/engine/daemon.py
tags: [engine, daemon, ipc]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Local AF_UNIX socket query daemon holding the embedding model and SQLite
connections warm for repeated CLI invocations, avoiding the per-invocation
model load cost (0.5-2s on CPU). Handles JSON requests over an AF_UNIX socket
(`.context/code-search.sock`, or a deterministic hashed runtime path when
the conventional path exceeds the `AF_UNIX` limit) serving search, symbol
resolution, implementations, graph traversal, and related-chunk queries;
every action's payload carries the shared freshness signal, while only the
`search` action additionally writes an audit entry and runs index-change
detection (with an in-process reload when required). A forwarded
search waits up to `CODE_SEARCH_WARMUP_WAIT_S` for the model instead of
silently serving the reduced lexical path, refuses to serve before the
index is `ready`, and applies the same compact/root-relative result shaping
as the in-process CLI. Implements both the server
([`QueryDaemon`](../../types/QueryDaemon.md)) and a synchronous client
([`DaemonClient`](../../types/DaemonClient.md)) used by CLI forwarding.

# Key Classes

- [`QueryDaemon`](../../types/QueryDaemon.md) — serves `ping`, `search`, `symbol`, `implementations`, `graph`, and `find_related` over an AF_UNIX socket, one thread per connection.
- [`DaemonClient`](../../types/DaemonClient.md) — synchronous AF_UNIX socket client used by CLI forwarding and daemon status.

# Key Functions

- [`default_socket_path`](../../functions/default_socket_path.md) — the daemon's socket path convention for a context directory.
- [`daemon_status`](../../functions/daemon_status.md) — report `{running, warm, socket, pid}` for a context directory's daemon.
- [`write_pidfile`](../../functions/write_pidfile.md), [`clear_pidfile`](../../functions/clear_pidfile.md) — daemon pidfile lifecycle.
- [`pid_is_alive`](../../functions/pid_is_alive.md) — whether the pidfile records a live process, so a still-initialising daemon is not mistaken for a crashed one.
- [`run_daemon_foreground`](../../functions/run_daemon_foreground.md) — run the daemon blocking in the foreground.

# Internal Helpers

`_daemon_freshness` mirrors the shared freshness signal so direct and
daemon-forwarded CLI output agree; `_pidfile_path`/`_read_pidfile` are
pidfile path/read helpers.
