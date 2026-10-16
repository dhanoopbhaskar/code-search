---
type: Function
title: "report_model_status"
description: "Generate the model warm/cold status report with latency breakdown."
resource: code_search/engine/model_status.py#report_model_status
tags: [embeddings, observability, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/model_status.py
    id: source-code
---

# Overview

Generates the model warm/cold status report with per-request latency
breakdown, mirroring the CLI schema for MCP responses. Defined in
[`engine.model_status`](../modules/engine/model_status.md).

# Signature

`def report_model_status(query_time_ms: int, warmup_time_ms: int, embedding_time_ms: int, ranking_time_ms: int, io_time_ms: int, is_first_request: bool, warmup_state: str \| None = None) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_time_ms` | `int` | Total query latency in milliseconds. |
| `warmup_time_ms` | `int` | Time elapsed since model initialization began. |
| `embedding_time_ms` | `int` | Time spent computing embeddings. |
| `ranking_time_ms` | `int` | Time spent ranking results. |
| `io_time_ms` | `int` | Time spent in I/O operations. |
| `is_first_request` | `bool` | Whether this is the first request since model initialization. |
| `warmup_state` | `str \| None` | Optional lifecycle state (`cold`/`warming`/`warm`/ `failed`/`disabled`); emitted as an additive key when provided. |

# Returns

dict with keys: - `state` (ModelState): Current model state (`warm`, `cold`, `initializing`) - `warmup_state` (str): Lifecycle state, present only when supplied - `warmup_time_ms` (integer): Time elapsed since model initialization began - `latency_breakdown` (dict): Per-phase latency breakdown with keys `cold_start`, `embedding`, `ranking`, `io` - `is_first_request` (boolean): Whether this is the first request since model initialization
