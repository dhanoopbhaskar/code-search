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
[`engine.classification`](/modules/engine/classification.md).

# Signature

`def file_role(file_path: str) -> FileRole`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | Path of the file to classify. |

# Returns

The [`FileRole`](/types/FileRole.md) for the file.
