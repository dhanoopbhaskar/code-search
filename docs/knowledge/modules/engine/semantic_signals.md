---
type: Module
title: "engine.semantic_signals"
description: "Package overlap, type sharing, and call-graph proximity signals for find_related relevance ranking."
resource: src/engine/semantic_signals.py
tags: [engine, ranking, find-related]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Computes three semantic signals from existing index data for
`find_related` relevance ranking: (1) package overlap (Jaccard similarity
of directory path segments), (2) type sharing (normalized signature
overlap), (3) call-graph proximity (inverse shortest-path distance in the
`CALLS` graph). Signals are combined with vector similarity via weighted
fusion.

# Key Classes

- [`SemanticSignals`](/types/SemanticSignals.md) — computed signals between anchor and candidate.
- [`RelevanceScore`](/types/RelevanceScore.md) — final combined relevance score.

# Key Functions

- [`compute_package_overlap`](/functions/compute_package_overlap.md) — Jaccard similarity of namespace directory segments.
- [`compute_type_sharing`](/functions/compute_type_sharing.md) — normalized signature comparison score.
- [`compute_call_proximity`](/functions/compute_call_proximity.md) — inverse call-graph depth between two symbols.
- [`compute_semantic_score`](/functions/compute_semantic_score.md) — compute all three signals for a candidate.
- [`compute_final_score`](/functions/compute_final_score.md) — fuse semantic signals with vector similarity.
- [`rerank_with_semantic`](/functions/rerank_with_semantic.md) — rerank vector results using semantic signals.
