---
type: Function
title: "chunk_rank_class"
description: "Classify a chunk as code/boilerplate/resource."
resource: code_search/engine/search.py#chunk_rank_class
tags: [search, ranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Classifies a chunk as code, boilerplate, or resource for ranking-tier
purposes. Defined in [`engine.search`](../modules/engine/search.md).

# Signature

`def chunk_rank_class(chunk_type: str \| None, chunk_node_type: str \| None) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `chunk_type` | `str \| None` | The indexer-assigned chunk type (`code`/`resource`/...), or `None`. |
| `chunk_node_type` | `str \| None` | The tree-sitter node type, or `None`. |

# Returns

The rank class label (e.g. `"code"`, `"boilerplate"`, `"resource"`).
