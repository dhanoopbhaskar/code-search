---
type: Class
title: "Reranker"
description: "Adjusts raw search scores using definition boost, test-file penalty, non-canonical penalty, and session weight."
resource: src/engine/reranking.py#Reranker
tags: [ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/reranking.py
    id: source-code
---

# Overview

Adjusts raw fused search scores using a definition boost, test-file
penalty, non-canonical-path penalty, file-role penalties, and session
weighting (via [`SessionDatabase`](/types/SessionDatabase.md)). Defined
in [`engine.reranking`](/modules/engine/reranking.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, session_db: SessionDatabase \| None = None, settings: Settings \| None = None) -> None` | Initialize the reranker, optionally wired to a session database. |
| `rerank(self, results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]` | Apply all adjustment rules to a candidate result list and re-sort. |
