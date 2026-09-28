---
type: Class
title: "FreshnessChecker"
description: "Computes a working-tree-vs-index staleness signal via stat baselines and optional rehashing."
resource: src/engine/freshness.py#FreshnessChecker
tags: [freshness, staleness]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/freshness.py
    id: source-code
---

# Overview

Computes whether the working tree is ahead of the index using a stat
fast-path (size/mtime match skips rehashing) with self-healing re-hash on
change. Defined in
[`engine.freshness`](/modules/engine/freshness.md); consumed by
[`IndexOrchestrator.run_incremental_index`](/types/IndexOrchestrator.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, metadata_store: IndexMetadataStore, ttl_seconds: float = 300.0) -> None` | Initialize the checker over an index metadata store with a cache TTL. |
| `check(self, repo_path: Path) -> dict[str, list[str]]` | Return `{deleted, new, modified}` file lists relative to the last index. |
