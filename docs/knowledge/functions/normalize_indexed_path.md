---
type: Function
title: "normalize_indexed_path"
description: "Resolve a path against the indexed repo root, collapsing symlinks and ../ segments."
resource: src/engine/paths.py#normalize_indexed_path
tags: [paths, find-related, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/paths.py
    id: source-code
---

# Overview

Resolves a caller-supplied path (absolute or project-relative) against
the indexed repo root, collapsing symlinks and `../` segments. Returns
`None` when the resolved path escapes the repo root. Defined in
[`engine.paths`](/modules/engine/paths.md).

# Signature

`def normalize_indexed_path(repo_root: Path, candidate: str) -> Path \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `repo_root` | `Path` | The indexed repository root. |
| `candidate` | `str` | The caller-supplied path to normalize. |

# Returns

The normalized absolute `Path`, or `None` if it escapes *repo_root*.
