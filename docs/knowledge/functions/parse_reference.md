---
type: Function
title: "parse_reference"
description: "Parse a query into a SymbolReference."
resource: src/engine/symbol_resolution.py#parse_reference
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Parses a raw query string into a
[`SymbolReference`](/types/SymbolReference.md) structure ahead of
resolution. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def parse_reference(query: str) -> SymbolReference`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text naming a symbol. |

# Returns

The parsed [`SymbolReference`](/types/SymbolReference.md).
