---
type: Function
title: "classify_entry_points"
description: "Store `is_entry_point` and `entry_point_reason` on every symbol."
resource: code_search/engine/graph_passes.py#classify_entry_points
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Store `is_entry_point` and `entry_point_reason` on every symbol.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def classify_entry_points(conn: Any, settings: Settings) -> int`

# Notes

Rules are evaluated in order and the first match wins: test symbol,
`main`, constructor, override/implementation, exported top-level symbol,
annotated framework handler, then a configured name/glob. Only top-level
public declarations count as exported API, so ordinary public methods are
not all classified as entry points.
