---
type: Function
title: "build_symbol_fqn"
description: "Construct a symbol's fully-qualified name."
resource: code_search/engine/symbols.py#build_symbol_fqn
tags: [symbols, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/symbols.py
    id: source-code
---

# Overview

Constructs a symbol's fully-qualified name from its module path and
enclosing-type chain. Defined in
[`engine.symbols`](../modules/engine/symbols.md).

# Signature

`def build_symbol_fqn(file_path: str, parent_fqn: str \| None, name: str, param_types: list[str] \| None = None) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | The symbol's file path (the FQN prefix). |
| `parent_fqn` | `str \| None` | The enclosing parent FQN, or `None` for a top-level symbol. |
| `name` | `str` | The symbol's short name. |
| `param_types` | `list[str] \| None` | Parameter type names appended as a `(params)` suffix, or `None`. |

# Returns

The fully-qualified name string.
