---
type: Class
title: "PathClass"
description: "StrEnum giving a file path's rank-relevant structural classification."
resource: src/engine/classification.py#PathClass
tags: [classification, paths, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

`StrEnum` giving the single rank-relevant classification of a file
path. Members order the demotion severity; `TEST`, `NON_CANONICAL`, and
`DTS` are pure path-shape signals while `BARREL` additionally consults
the index. Defined in
[`engine.classification`](../modules/engine/classification.md).

# Values

| Value | Description |
|---|---|
| `CANONICAL` | Default; ordinary shipped code. |
| `TEST` | Test-file path shape. |
| `NON_CANONICAL` | Non-canonical code (examples/legacy/generated/mocks). |
| `DTS` | TypeScript declaration file. |
| `BARREL` | Re-export/barrel file. |

# Methods

| Method | Description |
|---|---|
| `of(db: Any, file_path: str \| Path) -> PathClass` | Resolve the classification for *file_path*, consulting the index only for barrel detection. |
| `is_barrel(db: Any, file_path: str \| Path) -> bool` | Return whether *file_path* is a pure re-export barrel surface (`__init__.py`/`package-info.java` with zero definition chunks). |
