---
type: Function
title: "is_exact_fqn_match"
description: "Whether a candidate's FQN exactly matches the query's qualified name."
resource: src/engine/confidence.py#is_exact_fqn_match
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Evidence classifier: returns whether a candidate result's FQN exactly
matches the query's qualified name. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def is_exact_fqn_match(fqn: str, query: str) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `fqn` | `str` | The candidate result's fully-qualified name. |
| `query` | `str` | The raw query text. |

# Returns

`True` if the FQN exactly matches the query's qualified name portion.
