---
type: Function
title: "compute_package_overlap"
description: "Jaccard similarity of namespace directory segments."
resource: src/engine/semantic_signals.py#compute_package_overlap
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes the Jaccard similarity of namespace/directory path segments
between two symbols, one component of
[`SemanticSignals`](/types/SemanticSignals.md). Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def compute_package_overlap(path_a: str, path_b: str) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `path_a` | `str` | First file/module path. |
| `path_b` | `str` | Second file/module path. |

# Returns

Jaccard similarity in `[0.0, 1.0]`.
