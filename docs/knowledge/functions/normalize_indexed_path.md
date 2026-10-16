---
type: Function
title: "normalize_indexed_path"
description: "Resolve a path against the indexed repo root, collapsing symlinks and ../ segments."
resource: code_search/engine/paths.py#normalize_indexed_path
tags: [paths, find-related, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/paths.py
    id: source-code
---

# Overview

Resolves a caller-supplied path (absolute or project-relative) against
the indexed repo root, collapsing symlinks and `../` segments. Returns
`None` when the resolved path escapes the repo root. Defined in
[`engine.paths`](../modules/engine/paths.md).

# Signature

`def normalize_indexed_path(path: str, index_root: Path) -> Path \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `path` | `str` | Caller-supplied file path (absolute or project-relative). |
| `index_root` | `Path` | The indexed repository root. |

# Returns

The normalized absolute `Path`, or `None` if it escapes *index_root*.
