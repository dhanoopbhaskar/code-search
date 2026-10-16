---
type: Function
title: "resolve_with_signature"
description: "Signature-aware overload disambiguation."
resource: code_search/engine/symbol_resolution.py#resolve_with_signature
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/symbol_resolution.py
    id: source-code
---

# Overview

Disambiguates between overloaded candidates by comparing normalized
signatures (see
[`normalize_signature`](normalize_signature.md)) against the
query's supplied signature. Defined in
[`engine.symbol_resolution`](../modules/engine/symbol_resolution.md).

# Signature

`def resolve_with_signature(reference: SymbolReference, candidates: list[dict[str, Any]], *, max_candidates: int) -> ResolutionResult`

# Parameters

| Name | Type | Description |
|---|---|---|
| `reference` | `SymbolReference` | The parsed caller reference (with `signature` populated). |
| `candidates` | `list[dict[str, Any]]` | Raw candidate rows. |
| `max_candidates` | `int` | The bound applied to the ambiguous candidate list. |

# Returns

A `ResolutionResult`.
