---
type: Function
title: "scope_override"
description: "The neutral scope token that would include the intent's content type."
resource: src/engine/intent_detection.py#scope_override
tags: [query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/intent_detection.py
    id: source-code
---

# Overview

Returns the neutral `content` scope token that would include the given
intent's content type, used to suggest a corrective scope override.
Defined in
[`engine.intent_detection`](/modules/engine/intent_detection.md).

# Signature

`def scope_override(intent: ContentIntent) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `intent` | `ContentIntent` | The detected content intent. |

# Returns

The scope token string (e.g. `"docs"`, `"config"`, `"all"`).
