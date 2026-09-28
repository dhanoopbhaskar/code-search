---
type: Function
title: "detect_config_ddl_scent"
description: "Detect config/DDL scent signals in a query string."
resource: src/engine/scent_detection.py#detect_config_ddl_scent
tags: [ranking, scent, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/scent_detection.py
    id: source-code
---

# Overview

Detects configuration or schema (DDL) intent signals in a query string
via lexical keyword/phrase patterns, feeding
[`compute_scent_adjustment`](/functions/compute_scent_adjustment.md).
Defined in
[`engine.scent_detection`](/modules/engine/scent_detection.md).

# Signature

`def detect_config_ddl_scent(query: str) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The detected scent label, or `None` if no scent signal is present.
