---
type: Function
title: "normalize_signature"
description: "Parse and normalize a (params) signature."
resource: src/engine/symbol_resolution.py#normalize_signature
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Parses and normalizes a `(params)` signature string for overload
disambiguation comparison. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def normalize_signature(signature: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `signature` | `str` | The raw `(params)` signature text. |

# Returns

The normalized signature string.
