---
type: Function
title: "chunk_rank_class"
description: "Classify a chunk as code/boilerplate/resource."
resource: src/engine/search.py#chunk_rank_class
tags: [search, ranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Classifies a chunk as code, boilerplate, or resource for ranking-tier
purposes. Defined in [`engine.search`](/modules/engine/search.md).

# Signature

`def chunk_rank_class(chunk: dict[str, Any]) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `chunk` | `dict[str, Any]` | The chunk record to classify. |

# Returns

The rank class label (e.g. `"code"`, `"boilerplate"`, `"resource"`).
