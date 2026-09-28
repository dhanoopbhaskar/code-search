---
type: Function
title: "resolve_with_signature"
description: "Signature-aware overload disambiguation."
resource: src/engine/symbol_resolution.py#resolve_with_signature
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Disambiguates between overloaded candidates by comparing normalized
signatures (see
[`normalize_signature`](/functions/normalize_signature.md)) against the
query's supplied signature. Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def resolve_with_signature(candidates: list[dict[str, Any]], signature: str) -> dict[str, Any] \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `candidates` | `list[dict[str, Any]]` | Ambiguous candidate symbols sharing a name. |
| `signature` | `str` | The caller-supplied signature to match against. |

# Returns

The uniquely matching candidate, or `None` if none/multiple match.
