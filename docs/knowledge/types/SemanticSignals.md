---
type: Class
title: "SemanticSignals"
description: "Structural semantic signals (package overlap, type sharing, call proximity) between an anchor and a candidate symbol."
resource: src/engine/semantic_signals.py#SemanticSignals
tags: [ranking, semantics, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Structural semantic signals between an anchor symbol and a candidate —
package overlap, type sharing, and call-graph proximity — computed for
`find_related` reranking and consumed by
[`RelevanceScore`](RelevanceScore.md). Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `package_overlap` | `float` | Jaccard similarity of the anchor's and candidate's namespace directory segments. |
| `type_sharing` | `float` | Normalized signature (parameter + return type) overlap between the two symbols. |
| `call_proximity` | `float` | Inverse shortest-path distance between the symbols in the `CALLS` graph. |
