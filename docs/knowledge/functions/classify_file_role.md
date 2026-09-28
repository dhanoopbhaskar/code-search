---
type: Function
title: "classify_file_role"
description: "Classify a file's role for ranking adjustment, with evidence-based overrides."
resource: src/engine/file_role.py#classify_file_role
tags: [ranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/file_role.py
    id: source-code
---

# Overview

Classifies a file's role for ranking adjustment, applying evidence-based
overrides (e.g. promoting infra files that carry DB connection strings).
Defined in [`engine.file_role`](/modules/engine/file_role.md); wraps
[`classification.file_role`](/functions/file_role.md) with content-aware
overrides.

# Signature

`def classify_file_role(file_path: str, content: str \| None = None) -> FileRole`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | Path of the file to classify. |
| `content` | `str \| None` | Optional file content used for evidence-based overrides. |

# Returns

The resolved [`FileRole`](/types/FileRole.md).
