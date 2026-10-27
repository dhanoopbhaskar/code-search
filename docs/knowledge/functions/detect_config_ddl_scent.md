---
type: Function
title: "detect_config_ddl_scent"
description: "Detect config/DDL scent signals in a query string."
resource: code_search/engine/scent_detection.py#detect_config_ddl_scent
tags: [ranking, scent, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/scent_detection.py
    id: source-code
---

# Overview

Detects configuration or schema (DDL) intent signals in a query string
via lexical keyword/phrase patterns, feeding
[`compute_scent_adjustment`](compute_scent_adjustment.md). A single generic
token (`key`, `secret`, `connection`, `setting`) does not establish config
scent: an explicit `--content config`, a config noun phrase or config
filename, or two independent config tokens with no code vocabulary is
required. Defined in
[`engine.scent_detection`](../modules/engine/scent_detection.md).

# Signature

`def detect_config_ddl_scent(query: str) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The full user query string. |

# Returns

dict with keys: has_scent (bool), scent_type (str: `config`, `ddl`, or `neutral`), boost_factor (float), deprioritize_patterns (set), boost_patterns (set)
