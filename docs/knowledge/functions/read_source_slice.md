---
type: Function
title: "read_source_slice"
description: "Read a line-range slice of a source file."
resource: src/engine/graph.py#read_source_slice
tags: [graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/graph.py
    id: source-code
---

# Overview

Reads a line-range slice of a source file from disk, used to populate a
symbol's source code when returning definitions. Defined in
[`engine.graph`](/modules/engine/graph.md).

# Signature

`def read_source_slice(file_path: Path, start_line: int, end_line: int) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `Path` | Path to the source file. |
| `start_line` | `int` | 1-based inclusive start line. |
| `end_line` | `int` | 1-based inclusive end line. |

# Returns

The requested slice of source text.
