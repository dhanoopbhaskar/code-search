---
type: Function
title: "query_symbol_identifier"
description: "Extract a candidate symbol identifier from a query, if it looks like one."
resource: src/engine/search.py#query_symbol_identifier
tags: [search, query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Extracts a candidate symbol identifier from a query when the query looks
like a bare identifier rather than natural language. Defined in
[`engine.search`](/modules/engine/search.md).

# Signature

`def query_symbol_identifier(query: str) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The candidate identifier, or `None` if the query is not symbol-like.
