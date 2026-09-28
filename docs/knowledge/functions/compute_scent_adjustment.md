---
type: Function
title: "compute_scent_adjustment"
description: "Multiplicative ranking adjustment for a file under config/DDL scent."
resource: src/engine/scent_detection.py#compute_scent_adjustment
tags: [ranking, scent, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/scent_detection.py
    id: source-code
---

# Overview

Computes a multiplicative ranking adjustment for a file under
config/DDL scent — boosting `.properties`/`.sql`/`docker-compose.yml`
files and deprioritizing build metadata. Defined in
[`engine.scent_detection`](/modules/engine/scent_detection.md).

# Signature

`def compute_scent_adjustment(file_path: str, scent: str) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | The candidate file's path. |
| `scent` | `str` | The detected scent signal (e.g. `"config"`, `"ddl"`). |

# Returns

A multiplicative score adjustment factor.
