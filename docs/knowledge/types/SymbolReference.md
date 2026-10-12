---
type: Class
title: "SymbolReference"
description: "A caller-supplied name parsed into its matching components (raw, leaf, qualifier, signature, form)."
resource: src/engine/symbol_resolution.py#SymbolReference
tags: [symbols, resolution, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

A caller-supplied symbol name parsed into its matching components — the
raw text, bare leaf, parent qualifier, parsed signature, and syntactic
`form` — used by symbol-resolution disambiguation. Defined in
[`engine.symbol_resolution`](../modules/engine/symbol_resolution.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `raw` | `str` | The query trimmed of surrounding whitespace. |
| `leaf` | `str` | The bare member name after stripping `(params)`, `::` namespace, path, and trailing qualifier. |
| `parent_qualifier` | `str \| None` | The qualifier before the leaf for dotted / `::` forms, or `None` for a bare leaf. |
| `signature` | `dict[str, Any] \| None` | Parsed `(params)` object (`{arity, param_types, normalized}`) or `None`. |
| `form` | `str` | `exact_fqn` \| `qualified` \| `suffix` \| `bare_leaf`. |
