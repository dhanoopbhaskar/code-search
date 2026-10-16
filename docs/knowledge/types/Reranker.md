---
type: Class
title: "Reranker"
description: "Adjusts raw search scores using definition/file-role boosts, test-file and non-canonical penalties, and session weighting."
resource: code_search/engine/reranking.py#Reranker
tags: [ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/reranking.py
    id: source-code
---

# Overview

Adjusts raw fused search scores using a definition boost, test-file
penalty, non-canonical-path penalty, file-role penalties, and session
weighting (via [`SessionDatabase`](SessionDatabase.md)). Defined
in [`engine.reranking`](../modules/engine/reranking.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, session_db: SessionDatabase \| None = None, settings: Settings \| None = None) -> None` | Create a reranker wired to the graph and session databases. |
| `rerank(results: list[dict[str, Any]], query_terms: list[str] \| None = None, query: str \| None = None) -> list[dict[str, Any]]` | Reorder *results* in place by applying the definition, file-role, and authorization boosts, the test-file, DTS/barrel, and non-canonical penalties, and session weighting. |
