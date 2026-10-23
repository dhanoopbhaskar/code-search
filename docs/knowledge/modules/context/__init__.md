---
type: Module
title: "code_search.context"
description: "Manages the on-disk context directory holding all persistent index data, including the selected vector layout."
resource: code_search/context/__init__.py
tags: [context, storage, package]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/context/__init__.py
    id: source-code
---

# Overview

Manages the context directory structure that holds all persistent data
(SQLite databases, vector index files, and locks). Ensures the directory
and subdirectories exist, caches paths for programmatic access, and
provides both bulk path lookup and individual key-based retrieval.

The vector paths follow the configured index layout: `compact` resolves
`vectors.v2.bin` and `vectors.v2.meta` (plus the `.files` dictionary),
while `legacy` resolves `vectors.bin` and `vectors.meta.json`.

# Key Classes

- [`ContextManager`](../../types/ContextManager.md) — ensures the context directory structure exists and exposes cached paths for `graph.db`, `chunks.db`, `session.db`, `audit.db`, the layout-specific vector files, and `index.lock`.
