---
type: Function
title: "read_source_slice"
description: "Read a line-range slice of a source file."
resource: code_search/engine/graph.py#read_source_slice
tags: [graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph.py
    id: source-code
---

# Overview

Reads a line-range slice of a source file from disk, used to populate a
symbol's source code when returning definitions. Defined in
[`engine.graph`](../modules/engine/graph.md).

# Signature

`def read_source_slice(file_path: str, line_start: int \| None, line_end: int \| None) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | Path to the source file. |
| `line_start` | `int \| None` | 0-based start row, or `None`. |
| `line_end` | `int \| None` | 0-based end row, or `None`. |

# Returns

The requested slice of source text.
