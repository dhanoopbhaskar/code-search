---
type: Function
title: "strip_params"
description: "Remove the parameter-list suffix from a symbol name-shape string."
resource: src/engine/symbol_resolution.py#strip_params
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Name-shape helper: removes the parameter-list suffix (e.g.
`foo(int, str)` → `foo`) from a symbol reference string. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def strip_params(name: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `name` | `str` | A name possibly including a `(params)` suffix. |

# Returns

The name with any parameter-list suffix removed.
