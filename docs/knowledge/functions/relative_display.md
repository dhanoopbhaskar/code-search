---
type: Function
title: "relative_display"
description: "Return a file path relative to the index root in POSIX form for display."
resource: code_search/engine/graph_query.py#relative_display
tags: [graph, output, paths, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-21T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Used by the graph renderers to print paths relative to the indexed root with
forward slashes. A missing path renders as `?`; a falsy *root*, or a path
outside the root, falls back to the POSIX rendering of the stored spelling.
Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def relative_display(file_path: str | None, root: str | Path | None) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str \| None` | The stored file path. |
| `root` | `str \| Path \| None` | The indexed repository root. |

# Returns

The POSIX-style relative path, or `?` when *file_path* is empty.
