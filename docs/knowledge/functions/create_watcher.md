---
type: Function
title: "create_watcher"
description: "Convenience factory returning a fully-configured FileWatcher."
resource: code_search/engine/watcher.py#create_watcher
tags: [watcher, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/watcher.py
    id: source-code
---

# Overview

Convenience factory returning a fully-configured
[`FileWatcher`](../types/FileWatcher.md) for a repo path. Defined in
[`engine.watcher`](../modules/engine/watcher.md).

# Signature

`def create_watcher(root_path: Path, index_callback: Callable[[list[Path]], None], exclusion_patterns: set[str] \| None = None, settings: Settings \| None = None) -> FileWatcher`

# Parameters

| Name | Type | Description |
|---|---|---|
| `root_path` | `Path` | The directory to watch recursively. |
| `index_callback` | `Callable[[list[Path]], None]` | Callback invoked with changed files after the debounce window; typically triggers an incremental reindex. |
| `exclusion_patterns` | `set[str] \| None` | Directory/file-name parts to skip during scans. |
| `settings` | `Settings \| None` | Runtime settings; defaults to `from_env` when omitted. |

# Returns

A configured `FileWatcher` instance.
