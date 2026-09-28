---
type: Class
title: "SemanticSignals"
description: "Bundle of semantic relevance signals (similarity, coverage, coherence) computed per search result."
resource: src/engine/semantic_signals.py#SemanticSignals
tags: [ranking, semantics, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Bundle of semantic relevance signals — vector similarity, lexical
coverage, and file coherence — computed per search result and consumed
by [`RelevanceScore`](/types/RelevanceScore.md) and the confidence
pipeline. Defined in
[`engine.semantic_signals`](/modules/engine/semantic_signals.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `cosine_similarity` | `float` | Vector-search cosine similarity score. |
| `lexical_coverage` | `float` | Fraction of query tokens covered by the result. |
| `file_coherence` | `float` | Degree to which sibling chunks from the same file also matched. |
