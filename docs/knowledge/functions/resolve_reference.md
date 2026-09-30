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

Applies a tiered resolution strategy to rank candidates for a
[`SymbolReference`](../types/SymbolReference.md). Identity tiers resolve
only when exactly one declaration matches: `exact_fqn` →
`exact_conventional_fqn` → `unique_leaf` (bare references) →
`exact_parent_scope` (qualified references); when several declarations
match, the result is a ranked candidate list and never an auto-selected
declaration. Defined in
[`engine.symbol_resolution`](../modules/engine/symbol_resolution.md).

# Signature

`def resolve_reference(reference: SymbolReference, candidates: list[dict[str, Any]], *, max_candidates: int) -> ResolutionResult`

# Parameters

| Name | Type | Description |
|---|---|---|
| `reference` | `SymbolReference` | The parsed caller reference. |
| `candidates` | `list[dict[str, Any]]` | Raw candidate rows (with `parent_name` and `signature`). |
| `max_candidates` | `int` | The bound applied to the ambiguous candidate list. |

# Returns

A `ResolutionResult`.
