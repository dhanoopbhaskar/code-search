---
type: Function
title: "resolve_reference"
description: "Apply resolution tiers to rank candidates."
resource: src/engine/symbol_resolution.py#resolve_reference
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Applies a tiered resolution strategy (exact FQN > exact symbol name >
suffix/leaf match) to rank candidate symbols for a
[`SymbolReference`](/types/SymbolReference.md). Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def resolve_reference(reference: SymbolReference, symbol_store: SymbolStore) -> ResolutionResult`

# Parameters

| Name | Type | Description |
|---|---|---|
| `reference` | `SymbolReference` | The parsed symbol reference. |
| `symbol_store` | `SymbolStore` | Store used to look up candidate symbols. |

# Returns

The [`ResolutionResult`](/types/ResolutionResult.md).
