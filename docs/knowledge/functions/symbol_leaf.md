---
type: Function
title: "symbol_leaf"
description: "Return the trailing (leaf) segment of a dotted or qualified symbol name."
resource: src/engine/symbol_resolution.py#symbol_leaf
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Name-shape helper: returns the trailing (leaf) segment of a dotted or
qualified symbol name (e.g. `pkg.Class.method` → `method`). Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def symbol_leaf(fqn: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `fqn` | `str` | A fully- or partially-qualified symbol name. |

# Returns

The trailing leaf segment.
