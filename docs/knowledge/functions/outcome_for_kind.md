---
type: Function
title: "outcome_for_kind"
description: "Map an envelope kind to a user-visible outcome."
resource: src/engine/symbol_resolution.py#outcome_for_kind
tags: [symbols, resolution, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Maps a resolution envelope's `kind` to a user-visible outcome string.
Defined in
[`engine.symbol_resolution`](/modules/engine/symbol_resolution.md).

# Signature

`def outcome_for_kind(kind: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `kind` | `str` | The envelope kind produced by [`SymbolStore.resolve_name`](/types/SymbolStore.md). |

# Returns

The user-visible outcome label.
