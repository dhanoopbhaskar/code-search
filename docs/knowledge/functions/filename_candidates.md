---
type: Function
title: "filename_candidates"
description: "Chunk ids whose file name/stem equals the query."
resource: src/engine/match_boost.py#filename_candidates
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Returns chunk ids whose file name or stem exactly equals the query,
providing a high-confidence candidate set for filename-driven queries.
Defined in [`engine.match_boost`](../modules/engine/match_boost.md).

# Signature

`def filename_candidates(db: Any, context: QueryNameContext, content_scope: str) -> tuple[int, ...]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `Any` | The graph database exposing `chunks_fts` and `code_chunks`. |
| `context` | `QueryNameContext` | The request-scoped name context. |
| `content_scope` | `str` | The active content scope (`all`/`code`/`config`/ `docs`/`code_focused`). |

# Returns

A deterministic, de-duplicated tuple of matching chunk ids.
