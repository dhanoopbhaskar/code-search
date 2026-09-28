---
type: Class
title: "WarmupState"
description: "Tracks whether the embedding model has completed its warm-up pass."
resource: src/engine/embeddings.py#WarmupState
tags: [embeddings, model, state]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Tracks whether the embedding model has completed its warm-up pass (first
inference call, which is slower). Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `is_warm` | `bool` | Whether the model has completed its first inference. |
| `warmup_started_at` | `float \| None` | Monotonic timestamp when warm-up began. |
| `warmup_duration_ms` | `float \| None` | Duration of the warm-up call, in milliseconds. |
