---
type: Function
title: "rerank_with_semantic"
description: "Rerank vector results using semantic signals."
resource: src/engine/semantic_signals.py#rerank_with_semantic
tags: [ranking, semantics, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/semantic_signals.py
    id: source-code
---

# Overview

Reranks a list of vector-search results using
[`compute_semantic_score`](compute_semantic_score.md) and
[`compute_final_score`](compute_final_score.md) for each
candidate. Defined in
[`engine.semantic_signals`](../modules/engine/semantic_signals.md).

# Signature

`def rerank_with_semantic(vector_results: list[tuple[int, float]], anchor: dict[str, Any], db: GraphDatabase, settings: Settings, limit: int) -> list[dict[str, Any]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `vector_results` | `list[tuple[int, float]]` | List of (chunk_id, vector_similarity) from vector search |
| `anchor` | `dict[str, Any]` | Anchor symbol dict with fqn, file_path, symbol_id |
| `db` | `GraphDatabase` | Graph database |
| `settings` | `Settings` | Engine settings with semantic weights |
| `limit` | `int` | Maximum results to return |

# Returns

List of result dicts with final_score and semantic_signals, sorted by final_score desc
