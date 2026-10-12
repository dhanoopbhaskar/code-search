---
type: Class
title: "IndexLock"
description: "Cross-process file lock preventing concurrent index writes."
resource: src/engine/indexer.py#IndexLock
tags: [indexer, concurrency, locking]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/indexer.py
    id: source-code
---

# Overview

Cross-process file lock preventing concurrent index writes. Defined in
[`engine.indexer`](../modules/engine/indexer.md).

# Methods

| Method | Description |
|---|---|
| `__init__(lock_path: Path, timeout: float = 30.0) -> None` | Initialize a filesystem lock rooted at *lock_path*. |
| `try_acquire() -> bool` | Attempt one atomic lock acquisition without waiting. |
| `acquire() -> bool` | Poll for the lock until timeout or stale detection triggers a force release. |
| `release(force: bool = False) -> None` | Release the lock by deleting its file. |
| `is_locked: bool` (property) | Return whether the lock file currently exists on disk. |
| `acquired: bool` (property) | Return whether this process currently holds the lock. |
