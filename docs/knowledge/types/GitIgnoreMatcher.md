---
type: Class
title: "GitIgnoreMatcher"
description: "Matches paths against a repository's .gitignore files using Git's gitwildmatch semantics."
resource: code_search/engine/parser.py#GitIgnoreMatcher
tags: [parser, discovery, gitignore]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/parser.py
    id: source-code
---

# Overview

Evaluates `.gitignore` specs with `pathspec`'s `gitwildmatch`. Specs load
eagerly for a whole tree (default) or one directory at a time while discovery
walks, avoiding a second full-tree walk. Nested specs apply after their
parents, and a path under an ignored directory stays ignored even when a
deeper rule negates the path itself, as Git does. Used by
[`ASTParser`](ASTParser.md) when `respect_gitignore` is enabled. Defined in
[`engine.parser`](../modules/engine/parser.md).

# Methods

| Method | Description |
|---|---|
| `__init__(root_path: Path, *, load_tree: bool = True) -> None` | Create a matcher for *root_path*; `load_tree=False` defers loading to `add_directory`. |
| `add_directory(base: Path, filenames: Any) -> None` | Load *base*'s `.gitignore` when present and not already loaded. |
| `is_ignored(path: Path, *, is_dir: bool = False) -> bool` | Whether *path*, or an ancestor directory, is ignored. |
