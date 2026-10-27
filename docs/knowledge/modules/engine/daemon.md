---
type: Module
title: "engine.daemon"
description: "Local IPC query daemon (AF_UNIX socket or Windows named pipe) holding the embedding model and SQLite connections warm across CLI invocations, with a lifecycle-state file for readiness probes."
resource: code_search/engine/daemon.py
tags: [engine, daemon, ipc]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Local IPC query daemon holding the embedding model and SQLite connections
warm for repeated CLI invocations, avoiding the per-invocation model load cost
(0.5-2s on CPU). Handles JSON requests over a local endpoint — an `AF_UNIX`
socket on Linux/macOS (`.context/code-search.sock`, or a deterministic hashed
runtime path when the conventional path exceeds the `AF_UNIX` limit) and a
deterministic named pipe on Windows, which has no network listener — serving
search, symbol
resolution, implementations, graph traversal, and related-chunk queries;
every action's payload carries the shared freshness signal, while only the
`search` action additionally writes an audit entry and runs index-change
detection (with an in-process reload when required). A forwarded
search waits up to `CODE_SEARCH_WARMUP_WAIT_S` for the model instead of
silently serving the reduced lexical path, refuses to serve before the
index is `ready`, and applies the same compact/root-relative result shaping
as the in-process CLI, including `allow_weak`, `paths_only`, and the
`max_snippet_lines=0` no-content contract.

The endpoint is bound before component initialisation, and a
`code-search.state` file records the lifecycle (`starting`, `warming`,
`ready`, `failed`, `stopped`). A waiting client can therefore distinguish a
slow start from a crashed daemon, and non-`ping` requests arriving during
startup wait up to `startup_wait_s` (default 10 s) or receive a structured
`daemon is starting` response with `retry_after_ms`. Implements both the server
([`QueryDaemon`](../../types/QueryDaemon.md)) and a synchronous client
([`DaemonClient`](../../types/DaemonClient.md)) used by CLI forwarding.

# Key Classes

- [`QueryDaemon`](../../types/QueryDaemon.md) — serves `ping`, `search`, `symbol`, `implementations`, `graph`, `find_related`, and `shutdown` over the local endpoint, one thread per connection.
- [`DaemonClient`](../../types/DaemonClient.md) — synchronous IPC client used by CLI forwarding and daemon status.

# Key Functions

- [`default_socket_path`](../../functions/default_socket_path.md) — the daemon's socket path convention for a context directory.
- [`write_state`](../../functions/write_state.md), [`read_state`](../../functions/read_state.md), [`clear_state`](../../functions/clear_state.md) — daemon lifecycle-state file.
- [`daemon_status`](../../functions/daemon_status.md) — report `{running, warm, socket, pid}` for a context directory's daemon.
- [`write_pidfile`](../../functions/write_pidfile.md), [`clear_pidfile`](../../functions/clear_pidfile.md) — daemon pidfile lifecycle.
- [`pid_is_alive`](../../functions/pid_is_alive.md) — whether the pidfile records a live process, so a still-initialising daemon is not mistaken for a crashed one.
- [`run_daemon_foreground`](../../functions/run_daemon_foreground.md) — run the daemon blocking in the foreground.

# Internal Helpers

`_daemon_freshness` mirrors the shared freshness signal so direct and
daemon-forwarded CLI output agree; `_pidfile_path`/`_read_pidfile` are
pidfile path/read helpers, and `_state_path` locates the lifecycle-state
file. The related-chunk action delegates ranking to
[`engine.find_related`](find_related.md) so the daemon, CLI, and MCP
surfaces cannot drift.

# Platform Abstractions

The IPC endpoint differs per platform, so the concrete operations are named:

- [`default_socket_path`](../../functions/default_socket_path.md) — the endpoint
  convention for a context directory (`AF_UNIX` path on POSIX, `_pipe_name`
  address on Windows).
- [`prepare_socket_path`](../../functions/prepare_socket_path.md) — make the
  endpoint bindable: create the parent directory and remove a stale socket file
  left by an unclean exit. Named pipes are kernel objects with no filesystem
  entry, so there is nothing to prepare.
- [`endpoint_exists`](../../functions/endpoint_exists.md) — whether a socket file
  exists or a named-pipe listener is reachable.
- [`detached_spawn_kwargs`](../../functions/detached_spawn_kwargs.md) — `Popen`
  options that let the daemon outlive the shell: a new session on POSIX, and
  `DETACHED_PROCESS` plus `CREATE_NEW_PROCESS_GROUP` on Windows, where
  `start_new_session` is accepted but ignored.
- [`process_exists`](../../functions/process_exists.md) — a non-signalling
  liveness probe that goes through `OpenProcess` on Windows, because every
  signal except the two console events terminates the target there.

# Watch Mode

`QueryDaemon.__init__` and
[`run_daemon_foreground`](../../functions/run_daemon_foreground.md) accept
`watch=True`, which starts a
[`LiveIndexUpdater`](../../types/LiveIndexUpdater.md) so the warm process
re-indexes edited files instead of serving a stale index until the next
explicit `index` run. `_wake_pipe_accept` unblocks a pending named-pipe `accept`
so the serve loop can exit cleanly.
