---
type: Class
title: "ContentIntent"
description: "StrEnum for the content axis a query targets (DOCS, CONFIG, CODE, NEUTRAL)."
resource: code_search/engine/intent_detection.py#ContentIntent
tags: [query-analysis, intent, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/intent_detection.py
    id: source-code
---

# Overview

`StrEnum` for the content axis a query lexically targets: `DOCS`, `CONFIG`,
`CODE`, or `NEUTRAL`. Classification precedence is docs → config → code →
neutral. Defined in
[`engine.intent_detection`](../modules/engine/intent_detection.md);
produced by
[`classify_content_intent`](../functions/classify_content_intent.md).

# Values

| Value | Description |
|---|---|
| `DOCS` | Query asks about documentation. |
| `CONFIG` | Query asks about configuration or schema. |
| `CODE` | Query is a fuzzy source-level search (code vocabulary, an identifier-shaped token, or a single significant token). |
| `NEUTRAL` | No documentation, configuration, or code intent. |
