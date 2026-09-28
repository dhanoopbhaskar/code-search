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
`@app.route`), a high-trust signal for authorization-intent queries.
Defined in [`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def is_controller_endpoint(symbol: dict[str, Any]) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol` | `dict[str, Any]` | The candidate symbol record. |

# Returns

`True` if the symbol carries controller/endpoint markers.
