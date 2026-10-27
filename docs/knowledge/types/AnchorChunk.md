---
type: Class
title: "AnchorChunk"
description: "The indexed chunk selected as the anchor for a find-related query."
resource: code_search/engine/find_related.py#AnchorChunk
tags: [find-related, dataclass, anchor]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/find_related.py
    id: source-code
---

# Overview

A frozen dataclass carrying the chunk selected by
[`resolve_anchor_chunk`](../functions/resolve_anchor_chunk.md): the most
specific (smallest) chunk containing the requested line. Defined in
[`engine.find_related`](../modules/engine/find_related.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `stored_path` | `str` | The stored spelling of the resolved file path. |
| `chunk_id` | `int` | Primary key of the anchor chunk in `code_chunks`. |
| `fqn` | `str \| None` | Fully qualified symbol name of the chunk, when known. |
| `content` | `str` | The chunk source text. |
| `language` | `str \| None` | Chunk language identifier. |
| `line_start` | `int` | First source line covered by the chunk. |
| `line_end` | `int` | Last source line covered by the chunk. |
