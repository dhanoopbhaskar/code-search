---
type: Function
title: "build_scope_signal"
description: "Generate a surface-neutral scope message explaining an exclusion."
resource: code_search/engine/intent_detection.py#build_scope_signal
tags: [query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/intent_detection.py
    id: source-code
---

# Overview

Generates a surface-neutral message explaining why content was excluded
from search results (e.g. docs excluded from a code-only scope), and
recommending the [`scope_override`](scope_override.md).
Defined in
[`engine.intent_detection`](../modules/engine/intent_detection.md).

# Signature

`def build_scope_signal(intent: ContentIntent, effective: str, origin: str, suggested: str \| None) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `intent` | `ContentIntent` | The classified query intent. |
| `effective` | `str` | The effective scope applied to the search. |
| `origin` | `str` | `explicit`, `inferred`, or `default`. |
| `suggested` | `str \| None` | The recommended scope when no switch occurred, else `None`. |

# Returns

The actionable message, or `None` when no message is due.
