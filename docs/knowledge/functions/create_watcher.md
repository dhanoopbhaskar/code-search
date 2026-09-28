---
type: Function
title: "create_watcher"
description: "Convenience factory returning a fully-configured FileWatcher."
resource: src/engine/watcher.py#create_watcher
tags: [watcher, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/watcher.py
    id: source-code
---

# Overview

Convenience factory returning a fully-configured
[`FileWatcher`](/types/FileWatcher.md) for a repo path. Defined in
[`engine.watcher`](/modules/engine/watcher.md).

# Signature

`def create_watcher(repo_path: Path, callback: Callable, settings: Settings \| None = None) -> FileWatcher`

# Parameters

| Name | Type | Description |
|---|---|---|
| `repo_path` | `Path` | Directory to watch. |
| `callback` | `Callable` | Callback invoked with the set of changed files after debounce. |
| `settings` | `Settings \| None` | Optional configuration override. |

# Returns

A configured [`FileWatcher`](/types/FileWatcher.md) instance (not yet started).
