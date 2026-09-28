---
type: Module
title: "engine.watcher"
description: "Polling-based filesystem change detection with SHA256 hashing and debounce-window aggregation."
resource: src/engine/watcher.py
tags: [engine, watcher, filesystem]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/watcher.py
    id: source-code
---

# Overview

Implements polling-based filesystem change detection with SHA256 hashing
and debounce-window aggregation. Monitors a directory recursively,
accumulates changed files within a configurable quiet period, and fires a
user-supplied callback once the debounce window elapses. Exclusion
patterns skip common artifact directories.

# Key Classes

- [`FileWatcher`](/types/FileWatcher.md) — polls the filesystem for content changes using SHA256 hashing; debounces callbacks via `threading.Timer`.

# Key Functions

- [`create_watcher`](/functions/create_watcher.md) — convenience factory returning a fully-configured `FileWatcher`.
