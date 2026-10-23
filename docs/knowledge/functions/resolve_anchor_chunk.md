---
type: Function
title: "resolve_anchor_chunk"
description: "Resolve a file path and select the smallest indexed chunk containing a line."
resource: code_search/engine/find_related.py#resolve_anchor_chunk
tags: [find-related, function, resolution]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/find_related.py
    id: source-code
---

# Overview

Normalises the caller's path to its indexed spelling and selects the
smallest chunk whose line range contains the requested line, so a
method-body anchor embeds the method rather than the enclosing class.
Defined in [`engine.find_related`](../modules/engine/find_related.md).

# Signature

`def resolve_anchor_chunk(db: Any, file_path: str, line_number: int, index_root: Path) -> AnchorChunk | None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `Any` | The graph database. |
| `file_path` | `str` | Absolute or project-relative file path supplied by the caller. |
| `line_number` | `int` | Line within the file to anchor. |
| `index_root` | `Path` | Repository root used to normalise relative paths. |

# Returns

The matching [`AnchorChunk`](../types/AnchorChunk.md), or `None` when the
file is not indexed or no chunk contains the line.
