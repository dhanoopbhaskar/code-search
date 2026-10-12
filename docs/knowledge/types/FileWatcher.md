---
type: Class
title: "FileWatcher"
description: "Polls the filesystem for content changes using SHA256 hashing; debounces callbacks via threading.Timer."
resource: src/engine/watcher.py#FileWatcher
tags: [watcher, filesystem]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/watcher.py
    id: source-code
---

# Overview

Polls a directory recursively for content changes using SHA256 hashing,
aggregating changes within a debounce window before invoking a
user-supplied callback via `threading.Timer`. Defined in
[`engine.watcher`](../modules/engine/watcher.md).

# Methods

| Method | Description |
|---|---|
| `__init__(root_path: Path, on_change: Callable[[list[Path]], None], debounce_seconds: float \| None = None, exclusion_patterns: set[str] \| None = None, settings: Settings \| None = None) -> None` | Create a file watcher rooted at *root_path*. |
| `start() -> None` | Snapshot the current hashes and begin the polling loop in a thread. |
| `stop() -> None` | Stop the polling loop, cancel any pending timer, and join the thread. |
