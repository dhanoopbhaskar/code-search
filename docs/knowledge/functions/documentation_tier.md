---
type: Function
title: "documentation_tier"
description: "Classify a prose file's canonicality for documentation ranking."
resource: code_search/engine/classification.py#documentation_tier
tags: [classification, function, ranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/classification.py
    id: source-code
---

# Overview

Classifies a documentation chunk so the reranker can lift project docs and
demote vendored, generated, and nested variants under a docs-intent query.
Defined in [`engine.classification`](../modules/engine/classification.md).

# Signature

`def documentation_tier(file_path: str | Path) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str \| Path` | The stored file path of a documentation chunk. |

# Returns

`project` for root README/docs, `nested` for prose under `src/main`,
`generated` for generated help/API pages, `third_party` for
vendored/sample trees, and `other` otherwise.
