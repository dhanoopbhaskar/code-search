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
against the [`SymbolStore`](/types/SymbolStore.md). Defined in
[`engine.language`](/modules/engine/language.md).

# Signature

`def embedded_symbols(query: str, symbol_store: SymbolStore) -> list[str]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |
| `symbol_store` | `SymbolStore` | Store used to resolve candidate symbol names. |

# Returns

List of resolved symbol short names found in the query.
