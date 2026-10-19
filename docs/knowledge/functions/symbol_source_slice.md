---
type: Function
title: "symbol_source_slice"
description: "Return the source text spanned by a symbol row."
resource: code_search/engine/graph_query.py#symbol_source_slice
tags: [graph, function, source]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Thin wrapper over [`read_source_slice`](read_source_slice.md) that reads
`file_path`, `line_start`, and `line_end` from a symbol dict. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def symbol_source_slice(symbol: dict[str, Any]) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol` | `dict[str, Any]` | Symbol row carrying `file_path`, `line_start`, and `line_end`. |

# Returns

The source slice, or an empty string when the file cannot be read.
