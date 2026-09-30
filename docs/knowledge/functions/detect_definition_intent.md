---
type: Function
title: "detect_definition_intent"
description: "Detect definition phrasing and resolve its target."
resource: src/engine/language.py#detect_definition_intent
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Detects definition-seeking phrasing in a query (e.g. "where is X
defined") and resolves the referenced symbol target. Defined in
[`engine.language`](../modules/engine/language.md).

# Signature

`def detect_definition_intent(query: str, symbol_store: Any \| None = None) -> tuple[bool, str \| None]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw user query. |
| `symbol_store` | `Any \| None` | Optional symbol store used to resolve the captured definition target to a canonical FQN. |

# Returns

A tuple of `(definition_intent, definition_target)` where *definition_target* is the resolved FQN or `None` when no target was captured or resolved.
