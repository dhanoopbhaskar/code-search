---
type: Function
title: "classify_query"
description: "Classify a query as symbol-like or natural-language."
resource: code_search/engine/search.py#classify_query
tags: [search, query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Classifies a query as symbol-like (single identifier) or natural-language.
Defined in [`engine.search`](../modules/engine/search.md).

# Signature

`def classify_query(query: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The query class label: `"symbol"` for a single identifier, else `"natural"`.
