---
type: Function
title: "classify_content_intent"
description: "Classify a query lexically into docs/config/neutral."
resource: src/engine/intent_detection.py#classify_content_intent
tags: [query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/intent_detection.py
    id: source-code
---

# Overview

Classifies a query lexically into the documentation, configuration, or
neutral content intent, pure and deterministic. Defined in
[`engine.intent_detection`](/modules/engine/intent_detection.md).

# Signature

`def classify_content_intent(query: str) -> ContentIntent`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The detected [`ContentIntent`](/types/ContentIntent.md).
