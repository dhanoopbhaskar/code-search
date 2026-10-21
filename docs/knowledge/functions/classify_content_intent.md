---
type: Function
title: "classify_content_intent"
description: "Classify a query lexically into docs/config/code/neutral."
resource: code_search/engine/intent_detection.py#classify_content_intent
tags: [query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/intent_detection.py
    id: source-code
---

# Overview

Classifies a query lexically into the documentation, configuration, code, or
neutral content intent, pure and deterministic. The precedence is docs →
config → code → neutral: code intent is recognised from code-shaped signals
(source extensions, dotted names, code construct nouns such as `function` or
`interface`) so an identifier-like query is not misread as neutral. Defined in
[`engine.intent_detection`](../modules/engine/intent_detection.md).

# Signature

`def classify_content_intent(query: str) -> ContentIntent`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The user query text. |

# Returns

The classified `ContentIntent`.
