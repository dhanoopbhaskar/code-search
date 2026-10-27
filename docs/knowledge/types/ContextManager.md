---
type: Class
title: "ContextManager"
description: "Manages the on-disk context directory holding all persistent index data."
resource: code_search/context/__init__.py#ContextManager
tags: [context, state]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/context/__init__.py
    id: source-code
---

# Overview

Manages the context directory structure that holds all persistent data
(SQLite databases, vector index files, and the lock). Ensures the
directory and sub-directories exist, caches paths for programmatic
access, and provides both bulk path lookup and individual key-based
retrieval. Vector paths follow `settings.index_layout`: `compact` yields
`vectors.v2.bin`/`vectors.v2.meta` (plus `.files`), `legacy` yields
`vectors.bin`/`vectors.meta.json`. Defined in
[`context`](../modules/context/__init__.md).

# Class Attributes

| Attribute | Type | Description |
|---|---|---|
| `SUB_DATABASES` | `ClassVar[dict[str, str]]` | Mapping of logical database name (`graph`, `chunks`, `session`, `audit`) to its file name relative to the context directory. |

# Methods

| Method | Description |
|---|---|
| `__init__(settings: Settings \| None = None) -> None` | Create a context manager backed by the given settings. |
| `ensure() -> Path` | Create the context directory and all sub-directories, then cache paths. |
| `context_dir: Path` (property) | The resolved context directory path. |
| `paths: dict[str, Path]` (property) | A copy of the cached path mapping (name to file path). |
| `get_path(key: str) -> Path` | Return the cached path for the given logical name. |
