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
[`engine.watcher`](/modules/engine/watcher.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, watch_dir: Path, callback: Callable, debounce_seconds: float = 2.0, exclude_patterns: list[str] \| None = None) -> None` | Initialize the watcher over a directory with a debounce window. |
| `start() -> None` | Begin polling for changes in a background thread. |
| `stop() -> None` | Stop polling and cancel any pending debounce timer. |
