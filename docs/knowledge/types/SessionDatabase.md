---
type: Class
title: "SessionDatabase"
description: "Tracks code navigation events to enable session-based personalised reranking with exponential decay."
resource: src/engine/session.py#SessionDatabase
tags: [session, personalization, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/session.py
    id: source-code
---

# Overview

Tracks READ/WRITE navigation events per file and computes exponentially
decayed weights for personalised reranking. Defined in
[`engine.session`](/modules/engine/session.md); consumed by the
[`Reranker`](/types/Reranker.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, db_path: Path, settings: Settings \| None = None) -> None` | Initialize the session database at *db_path*. |
| `record_event(self, file_path: str, event_type: str) -> None` | Record a READ or WRITE event for a file. |
| `get_weights_for_files(self, file_paths: list[str]) -> dict[str, float]` | Return decayed session weights per file for reranking boost. |
