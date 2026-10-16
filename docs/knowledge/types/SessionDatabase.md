---
type: Class
title: "SessionDatabase"
description: "Tracks code navigation events to enable session-based personalised reranking with exponential decay."
resource: code_search/engine/session.py#SessionDatabase
tags: [session, personalization, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/session.py
    id: source-code
---

# Overview

Tracks READ/WRITE navigation events per file and computes exponentially
decayed weights for personalised reranking. Defined in
[`engine.session`](../modules/engine/session.md); consumed by the
[`Reranker`](Reranker.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db_path: Path, settings: Settings \| None = None) -> None` | Create a session database backed by the file at *db_path*. |
| `initialize() -> None` | Create the sessions table, indexes, and expired-row cleanup trigger. |
| `connect() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding the thread-local read connection. |
| `write_transaction() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding a dedicated connection for a write. |
| `record_event(file_path: str, event_type: str, session_id: str \| None = None) -> str` | Record a READ or WRITE event, returning the session ID. |
| `get_active_sessions() -> list[sqlite3.Row]` | Return all session rows, newest first, after purging expired ones. |
| `get_weights_for_files(file_paths: list[str]) -> list[dict[str, Any]]` | Compute decayed session weights for the given file paths. |
| `track_git_changes(repo_path: Path) -> int` | Run `git status --porcelain` and record WRITE events for modified files. |
| `close() -> None` | Close the thread-local connection if one has been opened. |
