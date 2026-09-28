---
type: Module
title: "engine.model_status"
description: "Generates model warm/cold status reports with per-request latency breakdown for MCP responses."
resource: src/engine/model_status.py
tags: [engine, embeddings, observability]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/model_status.py
    id: source-code
---

# Overview

Generates model warm/cold status reports for MCP responses. Mirrors the
CLI schema, surfacing per-request latency breakdown and model state
(warm, cold, initializing) in every ranked response.

# Key Classes

- [`ModelState`](/types/ModelState.md) — `StrEnum` for the current model state (`WARM`, `COLD`, `INITIALIZING`).

# Key Functions

- [`report_model_status`](/functions/report_model_status.md) — generate the model warm/cold status report with latency breakdown.
