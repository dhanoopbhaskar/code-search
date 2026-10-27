---
type: Module
title: "engine.paths"
description: "Path normalization and stored-path resolution for find-related and symbol lookups: case-insensitive filesystem canonicalisation and repo-relative, location-independent spellings."
resource: code_search/engine/paths.py
tags: [engine, paths, find-related]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
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

Two further rules keep the index independent of where the repository is
checked out: stored paths are always written in POSIX spelling
([`portable_path`](../../functions/portable_path.md)) because they are compared
as substrings, embedded in FQNs, and ranked by shape; and ranking signals see
the repo-relative spelling
([`repo_relative_path`](../../functions/repo_relative_path.md)) so a checkout
inside a directory named after a query term cannot floor every chunk's score.

# Key Functions

- [`normalize_indexed_path`](../../functions/normalize_indexed_path.md) — resolve a path against the indexed repo root, collapsing symlinks and `../` segments.
- [`resolve_stored_path`](../../functions/resolve_stored_path.md) — return the stored `code_chunks.file_path` spelling for a candidate path.
- [`portable_path`](../../functions/portable_path.md) — render a path in POSIX spelling, so one separator convention reaches the index on every platform.
- [`repo_relative_path`](../../functions/repo_relative_path.md) — return a stored path relative to the indexed root (unchanged when it lies outside), so path-shape ranking signals never observe the checkout location.

# Internal Helpers

`_is_within` tests path containment; `_row_value` extracts a column value
from a sqlite3 row or tuple; `_canonical_case` walks existing directory
entries to restore on-disk case.
