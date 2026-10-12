---
type: Function
title: "is_controller_endpoint"
description: "Whether a symbol looks like a web controller/route endpoint (a high-trust signal for authorization-intent queries)."
resource: src/engine/confidence.py#is_controller_endpoint
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Evidence classifier: detects whether a symbol looks like a web
controller/route endpoint (e.g. annotated with `@GetMapping`,
`@PostMapping`, or a file whose stem ends with `Controller`), a high-trust
signal for authorization-intent queries.
Defined in [`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def is_controller_endpoint(is_definition: bool, content: str, file_path: str) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `is_definition` | `bool` | Whether the chunk is the symbol's definition site. |
| `content` | `str` | The chunk source (already in memory). |
| `file_path` | `str` | The containing file path. |

# Returns

`True` when the chunk is a controller endpoint definition.
