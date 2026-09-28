---
type: Class
title: "ResolutionResult"
description: "Outcome of resolving a name query to a symbol: exact match, ambiguous candidates, or not found."
resource: src/engine/symbol_resolution.py#ResolutionResult
tags: [symbols, resolution, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Represents the outcome of resolving a name query to a symbol: an exact
match, an ambiguous set of candidates, or a not-found result. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md);
consumed by [`SymbolStore.resolve_name`](/types/SymbolStore.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `outcome` | `str` | One of `"resolved"`, `"ambiguous"`, `"not_found"`. |
| `symbol` | `dict \| None` | The resolved symbol, if `outcome == "resolved"`. |
| `candidates` | `list[dict]` | Candidate matches when ambiguous. |
