---
type: Class
title: "ModelState"
description: "StrEnum for the current embedding model state (WARM, COLD, INITIALIZING)."
resource: src/engine/model_status.py#ModelState
tags: [embeddings, observability, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/model_status.py
    id: source-code
---

# Overview

`StrEnum` for the current embedding model state: `WARM`, `COLD`, or
`INITIALIZING`. Defined in
[`engine.model_status`](/modules/engine/model_status.md); reported by
[`report_model_status`](/functions/report_model_status.md) and surfaced
in every ranked MCP response.
