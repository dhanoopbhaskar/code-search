---
type: Function
title: "build_scope_signal"
description: "Generate a surface-neutral scope message explaining an exclusion."
resource: src/engine/intent_detection.py#build_scope_signal
tags: [query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/intent_detection.py
    id: source-code
---

# Overview

Generates a surface-neutral message explaining why content was excluded
from search results (e.g. docs excluded from a code-only scope), and
recommending the [`scope_override`](/functions/scope_override.md).
Defined in
[`engine.intent_detection`](/modules/engine/intent_detection.md).

# Signature

`def build_scope_signal(intent: ContentIntent, current_scope: str) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `intent` | `ContentIntent` | The detected content intent. |
| `current_scope` | `str` | The `content` scope currently applied to the search. |

# Returns

A human-readable scope message, or `None` when no signal is warranted.
