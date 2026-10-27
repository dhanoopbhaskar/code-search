---
type: Module
title: "engine.paths"
description: "Path normalization and stored-path resolution for find-related and symbol lookups, including case-insensitive filesystem canonicalisation."
resource: code_search/engine/paths.py
tags: [engine, paths, find-related]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/paths.py
    id: source-code
---

# Overview

Path normalization and stored-path resolution for the `find_related` MCP
tool. Resolves caller-supplied file paths (absolute or project-relative)
to the indexed location spelling. All functions are pure stdlib-only
utilities using `pathlib` and `sqlite3`, returning `None` for paths that
escape the index root rather than raising errors.

On case-insensitive filesystems, `normalize_indexed_path` rewrites a
case-variant input (`src/authservice.java`) to the on-disk spelling
(`src/AuthService.java`) so it matches the stored path. Components the
filesystem cannot resolve are left untouched, and an ambiguous
case-insensitive match keeps the caller's spelling.

# Key Functions

- [`normalize_indexed_path`](../../functions/normalize_indexed_path.md) — resolve a path against the indexed repo root, collapsing symlinks and `../` segments.
- [`resolve_stored_path`](../../functions/resolve_stored_path.md) — return the stored `code_chunks.file_path` spelling for a candidate path.

# Internal Helpers

`_is_within` tests path containment; `_row_value` extracts a column value
from a sqlite3 row or tuple; `_canonical_case` walks existing directory
entries to restore on-disk case.
