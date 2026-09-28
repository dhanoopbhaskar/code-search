---
type: Function
title: "compute_semantic_score"
description: "Compute all three semantic signals for a candidate."
resource: src/engine/semantic_signals.py#compute_semantic_score
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes all three semantic signals — package overlap, type sharing, call
proximity — for a candidate, bundling them into a
[`SemanticSignals`](/types/SemanticSignals.md) instance. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Signature

`def compute_semantic_score(edge_store: EdgeStore, source: dict[str, Any], candidate: dict[str, Any]) -> SemanticSignals`

# Parameters

| Name | Type | Description |
|---|---|---|
| `edge_store` | `EdgeStore` | Graph edge store for call-proximity lookups. |
| `source` | `dict[str, Any]` | The source/reference symbol. |
| `candidate` | `dict[str, Any]` | The candidate symbol being scored. |

# Returns

A populated [`SemanticSignals`](/types/SemanticSignals.md) instance.
