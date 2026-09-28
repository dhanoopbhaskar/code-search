---
type: Function
title: "is_exact_symbol_match"
description: "Whether a candidate's short symbol name exactly matches a query token."
resource: src/engine/confidence.py#is_exact_symbol_match
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Evidence classifier: returns whether a candidate's short symbol name
exactly matches a query token. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def is_exact_symbol_match(symbol_name: str, query: str) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol_name` | `str` | The candidate's short symbol name. |
| `query` | `str` | The raw query text. |

# Returns

`True` if a query token exactly equals the symbol name.
