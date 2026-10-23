---
type: Function
title: "config_tier"
description: "Classify a configuration file's canonicality for config ranking."
resource: code_search/engine/classification.py#config_tier
tags: [classification, function, ranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/classification.py
    id: source-code
---

# Overview

Classifies a configuration chunk so the reranker can boost primary
application configuration and demote test, sample, and generated variants
under a config-intent query. Defined in
[`engine.classification`](../modules/engine/classification.md).

# Signature

`def config_tier(file_path: str | Path) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str \| Path` | The stored file path of a configuration chunk. |

# Returns

`primary` for module-level `application*`/`bootstrap*` files and module
`config/` resources, `test` for test resources, `sample` for
sample/example/demo trees, `generated` for build output, and `other`
otherwise.
