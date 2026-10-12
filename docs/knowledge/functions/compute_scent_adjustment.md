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
config/DDL scent — under config scent boosting `.properties`/`.sql`/
`docker-compose.yml` files, under DDL scent boosting only `.sql`/
`docker-compose.yml`, and deprioritizing build metadata. Defined in
[`engine.scent_detection`](../modules/engine/scent_detection.md).

# Signature

`def compute_scent_adjustment(file_role: str, file_extension: str, scent_type: str, boost_factor: float) -> float`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_role` | `str` | The classified role (code/config/infra/resource/docs). |
| `file_extension` | `str` | The file extension (`.properties`) or bare filename (e.g. `pom.xml`). |
| `scent_type` | `str` | `config`, `ddl`, or `neutral`. |
| `boost_factor` | `float` | The configured boost factor ([0.0, 2.0]). |

# Returns

A multiplier to apply to the file's weighted score; `1.0` means no adjustment.
