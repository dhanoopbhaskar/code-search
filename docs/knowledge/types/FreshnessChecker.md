---
type: Class
title: "FreshnessChecker"
description: "Computes a working-tree-vs-index staleness signal via stat baselines and optional rehashing."
resource: code_search/engine/freshness.py#FreshnessChecker
tags: [freshness, staleness]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/freshness.py
    id: source-code
---

# Overview

Computes whether the working tree is ahead of the index using a stat
fast-path (size/mtime match skips rehashing) with self-healing re-hash on
change. In `deferred` freshness mode an expired cache is served immediately
with `refreshing: true` while one background thread recomputes it; the
effective TTL is at least twice the last scan duration. Defined in
[`engine.freshness`](../modules/engine/freshness.md); consumed by
[`IndexOrchestrator.index_codebase`](IndexOrchestrator.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, metadata: IndexMetadataStore, parser: ASTParser, context_dir: Path, settings: Settings \| None = None) -> None` | Create a freshness checker for *context_dir*. |
| `signal() -> dict[str, Any]` | Return the current freshness signal, TTL-cached per metadata; deferred mode adds `refreshing` and serves the cached signal while a background scan runs. |
| `mark_clean() -> None` | Seed a current (non-stale) cached signal after a successful index. |
