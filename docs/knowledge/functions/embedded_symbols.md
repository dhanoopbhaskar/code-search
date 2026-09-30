---
type: Function
title: "embedded_symbols"
description: "Resolved symbol short names embedded in a natural-language query."
resource: src/engine/language.py#embedded_symbols
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Extracts symbol short names embedded within a natural-language query
(e.g. `HybridSearch` mentioned inside a prose question) and resolves them
against the [`SymbolStore`](../types/SymbolStore.md). Defined in
[`engine.language`](../modules/engine/language.md).

# Signature

`def embedded_symbols(query: str, symbol_store: Any \| None = None) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw user query (case preserved, so `StateManager` in prose resolves while `statemanager` does not). |
| `symbol_store` | `Any \| None` | An optional symbol store used for exact resolution; `None` returns an empty list (the caller owns the gate). |

# Returns

The sorted unique resolved symbol names.
