---
type: Function
title: "file_role"
description: "Resolve a file's role from path/filename signals alone."
resource: src/engine/classification.py#file_role
tags: [classification, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

Resolves a file's structural role from path/filename signals alone,
without inspecting file content. Defined in
[`engine.classification`](../modules/engine/classification.md).

# Signature

`def file_role(file_path: str \| Path, analysis_paths: set[str] \| None = None) -> FileRole`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str \| Path` | The stored file path of the candidate chunk. |
| `analysis_paths` | `set[str] \| None` | Optional extension of the built-in analysis artifact path-segment set (`CODE_SEARCH_ANALYSIS_ARTIFACT_PATHS`); when `None`, only the built-in conventions apply. |

# Returns

The resolved `FileRole`.
