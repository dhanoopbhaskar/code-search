---
type: Class
title: "WarmupState"
description: "Lifecycle state of the in-process embedding model (cold, warming, warm, failed, disabled)."
resource: code_search/engine/embeddings.py#WarmupState
tags: [embeddings, model, state]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

`StrEnum` tracking the lifecycle state of the in-process embedding model. Defined in
[`engine.embeddings`](../modules/engine/embeddings.md).

# Values

| Value | Description |
|---|---|
| `COLD` | No model load has started. |
| `WARMING` | A background model load is in flight. |
| `WARM` | A usable model is resident in memory. |
| `FAILED` | The model load raised. |
| `DISABLED` | The model is explicitly off (`--no-model`). |
