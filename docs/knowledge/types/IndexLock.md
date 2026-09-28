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
[`engine.indexer`](/modules/engine/indexer.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, lock_path: Path) -> None` | Initialize the lock at *lock_path*. |
| `acquire(self, timeout: float = 10.0) -> bool` | Attempt to acquire the lock, retrying until *timeout*. |
| `release() -> None` | Release the lock and remove the lock file. |
| `__enter__` / `__exit__` | Context-manager protocol wrapping acquire/release. |
