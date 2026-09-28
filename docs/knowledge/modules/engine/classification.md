---
type: Module
title: "engine.classification"
description: "Shared file-class classification (FileRole, ContentType, PathClass) used by all ranking passes."
resource: src/engine/classification.py
tags: [engine, ranking, classification]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

File-class classification shared by ranking passes. Every consumer that
adjusts a chunk by file shape resolves the file into one of the
[`PathClass`](/types/PathClass.md) members, so classification vocabulary
and behavior live in exactly one place. Shared by `file_role`,
`content_type`, and barrel-file classification logic.

# Key Classes

- [`FileRole`](/types/FileRole.md) — `StrEnum` for file-role classification (`CODE`, `MODEL`, `DTO`, `ASSEMBLER`, `EXCEPTION`, `INFRA`, `CONFIG`, `RESOURCE`, `DOCS`, `ANALYSIS`).
- [`ContentType`](/types/ContentType.md) — `StrEnum` for content axis (`CODE`, `CONFIG`, `DOCS`).
- [`PathClass`](/types/PathClass.md) — `StrEnum` for rank-relevant classification (`CANONICAL`, `TEST`, `NON_CANONICAL`, `DTS`, `BARREL`).

# Key Functions

- [`content_type`](/functions/content_type.md) — classify a file into the content axis.
- [`file_role`](/functions/file_role.md) — resolve a file's role from path/filename signals alone.
