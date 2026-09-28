---
type: Module
title: "engine.scent_detection"
description: "Detects configuration/DDL intent signals in queries and returns boost/deprioritization multipliers for ranking."
resource: src/engine/scent_detection.py
tags: [engine, ranking, intent]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/scent_detection.py
    id: source-code
---

# Overview

Detects configuration or schema (DDL) intent signals in user queries,
returning boost/deprioritization multipliers for ranking. Signals are
lexical patterns (keywords, phrases, explicit flags like
`--content config`) with no I/O or model dependency. Applies type-aware
file-extension matching: under config scent, `.properties`/`.sql`
/`docker-compose.yml` files are boosted while build metadata
(`pom.xml`, `package-lock.json`) are deprioritized.

# Key Functions

- [`compute_scent_adjustment`](/functions/compute_scent_adjustment.md) — multiplicative ranking adjustment for a file under config/DDL scent.
- [`detect_config_ddl_scent`](/functions/detect_config_ddl_scent.md) — detect config/DDL scent signals in a query string.
