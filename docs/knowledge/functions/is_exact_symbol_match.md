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
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def is_exact_symbol_match(query_identifier: str \| None, fqn: str, ambiguous: bool) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query_identifier` | `str \| None` | The query's bare identifier, or `None`. |
| `fqn` | `str` | The candidate chunk's fully qualified name. |
| `ambiguous` | `bool` | Whether the identifier resolves to multiple candidates. |

# Returns

`True` when the unqualified query equals the candidate's short name.
