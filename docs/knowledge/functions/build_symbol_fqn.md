---
type: Function
title: "build_symbol_fqn"
description: "Construct a symbol's fully-qualified name."
resource: src/engine/symbols.py#build_symbol_fqn
tags: [symbols, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbols.py
    id: source-code
---

# Overview

Constructs a symbol's fully-qualified name from its module path and
enclosing-type chain. Defined in
[`engine.symbols`](/modules/engine/symbols.md).

# Signature

`def build_symbol_fqn(module_path: str, ancestor_names: list[str], symbol_name: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `module_path` | `str` | Dotted module path. |
| `ancestor_names` | `list[str]` | Chain of enclosing type/function names. |
| `symbol_name` | `str` | The symbol's own short name. |

# Returns

The fully-qualified name string.
