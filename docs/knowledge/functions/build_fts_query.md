---
type: Function
title: "build_fts_query"
description: "Build an FTS5 MATCH expression from decomposed sub-words."
resource: src/engine/search.py#build_fts_query
tags: [search, bm25, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Builds a SQLite FTS5 `MATCH` expression from decomposed sub-words (see
[`decompose_query`](/functions/decompose_query.md)), used by
[`BM25Search.search`](/types/BM25Search.md). Defined in
[`engine.search`](/modules/engine/search.md).

# Signature

`def build_fts_query(subwords: list[str]) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `subwords` | `list[str]` | Decomposed query sub-words. |

# Returns

The FTS5 `MATCH` query expression string.
