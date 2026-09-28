---
type: Class
title: "RelevanceScore"
description: "Composite relevance score combining semantic signals into a single ranking value."
resource: src/engine/semantic_signals.py#RelevanceScore
tags: [ranking, semantics, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Composite relevance score combining [`SemanticSignals`](/types/SemanticSignals.md)
into a single ranking value used during reranking. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `score` | `float` | Final composite relevance score. |
| `signals` | `SemanticSignals` | The underlying signal bundle the score was derived from. |
