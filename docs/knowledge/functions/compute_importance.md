---
type: Function
title: "compute_importance"
description: "Store the adapted weighted-degree importance score on every symbol."
resource: code_search/engine/graph_passes.py#compute_importance
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Store the adapted weighted-degree importance score on every symbol.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def compute_importance(conn: Any) -> int`

# Notes

The formula is documented and deterministic:

        importance = sqrt(incoming CALLS + USAGE)
                   * 0.1 for private symbols
                   * 0.1 when the name is defined in >= 5 distinct files
                   * 10  for a descriptive name of at least 8 characters
                   * 0.1 for test scaffolding

Scores are rounded to six decimals so the same index always produces the
same values.
