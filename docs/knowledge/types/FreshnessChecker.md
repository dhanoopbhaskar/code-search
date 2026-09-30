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
[`engine.freshness`](../modules/engine/freshness.md); consumed by
[`IndexOrchestrator.index_codebase`](IndexOrchestrator.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, metadata: IndexMetadataStore, parser: ASTParser, context_dir: Path, settings: Settings \| None = None) -> None` | Create a freshness checker for *context_dir*. |
| `signal() -> dict[str, Any]` | Return the current freshness signal, TTL-cached per metadata. |
| `mark_clean() -> None` | Seed a current (non-stale) cached signal after a successful index. |
