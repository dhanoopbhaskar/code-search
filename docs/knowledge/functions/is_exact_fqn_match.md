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
[`engine.confidence`](../modules/engine/confidence.md).

# Signature

`def is_exact_fqn_match(qualified_name: str \| None, fqn: str) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `qualified_name` | `str \| None` | The query's qualified form, or `None`. |
| `fqn` | `str` | The candidate chunk's fully qualified name. |

# Returns

`True` when the qualified query names the candidate exactly.
