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
Defined in [`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def filename_candidates(db: GraphDatabase, query: str) -> list[int]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `GraphDatabase` | Graph database to query. |
| `query` | `str` | The raw query text. |

# Returns

List of matching chunk ids.
