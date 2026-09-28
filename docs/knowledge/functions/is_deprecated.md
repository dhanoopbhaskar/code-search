---
type: Function
title: "is_deprecated"
description: "Whether declared_rules carries a deprecation marker."
resource: src/engine/symbol_resolution.py#is_deprecated
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Returns whether a symbol's `declared_rules` metadata carries a
deprecation marker (e.g. `@Deprecated` annotation). Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def is_deprecated(symbol: dict[str, Any]) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol` | `dict[str, Any]` | The symbol record to check. |

# Returns

`True` if the symbol is marked deprecated.
