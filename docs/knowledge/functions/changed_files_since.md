---
type: Function
title: "changed_files_since"
description: "Return working-tree paths changed relative to git ref."
resource: code_search/engine/graph_surface.py#changed_files_since
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Return working-tree paths changed relative to git `ref`.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def changed_files_since(root: Path, ref: str) -> list[str]`

# Parameters

| Name | Description |
|---|---|
| `root` | Repository root to run git in. |
| `ref` | A commit, branch, or other ref accepted by `git diff`. |

# Returns

Index-relative paths in git's output order.

# Raises

- RuntimeError: When git is unavailable or `ref` cannot be resolved.
