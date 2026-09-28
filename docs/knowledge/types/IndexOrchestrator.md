---
type: Class
title: "IndexOrchestrator"
description: "Coordinates full and incremental indexing: parsing, symbol/edge extraction, embedding, and FTS population."
resource: src/engine/indexer.py#IndexOrchestrator
tags: [indexer, orchestration, core]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/indexer.py
    id: source-code
---

# Overview

Coordinates full and incremental indexing: file discovery, tree-sitter
parsing, symbol/edge extraction, chunk embedding, and FTS5 population.
Defined in [`engine.indexer`](/modules/engine/indexer.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, repo_path: Path, db: GraphDatabase, settings: Settings \| None = None) -> None` | Initialize the orchestrator over a repo and graph database. |
| `run_full_index() -> dict[str, Any]` | Index every eligible file from scratch, returning summary stats. |
| `run_incremental_index() -> dict[str, Any]` | Re-index only files changed since the last index, using [`FreshnessChecker`](/types/FreshnessChecker.md). |
| `index_file(self, file_path: Path) -> None` | Parse, extract, embed, and store a single file's chunks/symbols/edges. |
