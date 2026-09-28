---
type: Class
title: "SymbolReference"
description: "A resolved or candidate reference to a symbol, used by symbol_resolution's disambiguation logic."
resource: src/engine/symbol_resolution.py#SymbolReference
tags: [symbols, resolution, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Represents a resolved or candidate reference to a symbol by name,
carrying enough context (FQN, kind, file) to disambiguate between
multiple matches. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `fqn` | `str` | Fully-qualified name of the referenced symbol. |
| `kind` | `str` | Symbol kind (function, class, method, etc.). |
| `file_path` | `str` | File where the symbol is declared. |
| `line` | `int` | Declaration line number. |
