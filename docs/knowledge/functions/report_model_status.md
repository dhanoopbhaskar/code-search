---
type: Function
title: "report_model_status"
description: "Generate the model warm/cold status report with latency breakdown."
resource: src/engine/model_status.py#report_model_status
tags: [embeddings, observability, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/model_status.py
    id: source-code
---

# Overview

Generates the model warm/cold status report with per-request latency
breakdown, mirroring the CLI schema for MCP responses. Defined in
[`engine.model_status`](/modules/engine/model_status.md).

# Signature

`def report_model_status(warmup_state: WarmupState, request_duration_ms: float) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `warmup_state` | `WarmupState` | The embedding model's current warm-up state. |
| `request_duration_ms` | `float` | Total duration of the current request. |

# Returns

A dict with `state` ([`ModelState`](/types/ModelState.md)) and latency breakdown fields.
