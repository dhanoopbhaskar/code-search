---
type: Module
title: "src.context"
description: "Manages the on-disk context directory holding all persistent index data."
resource: src/context/__init__.py
tags: [context, storage, package]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/context/__init__.py
    id: source-code
---

# Overview

Manages the context directory structure that holds all persistent data
(SQLite databases, vector index files, and locks). Ensures the directory
and subdirectories exist, caches paths for programmatic access, and
provides both bulk path lookup and individual key-based retrieval.

# Key Classes

- [`ContextManager`](/types/ContextManager.md) — ensures the context directory structure exists and exposes cached paths for `graph.db`, `session.db`, `audit.db`, `vectors.bin`, `vectors.meta.json`, and `index.lock`.
