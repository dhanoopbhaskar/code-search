---
type: Class
title: "ContentIntent"
description: "StrEnum for the content axis a query targets (DOCS, CONFIG, NEUTRAL)."
resource: code_search/engine/intent_detection.py#ContentIntent
tags: [query-analysis, intent, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/intent_detection.py
    id: source-code
---

# Overview

`StrEnum` for the content axis a query lexically targets: `DOCS`,
`CONFIG`, or `NEUTRAL`. Defined in
[`engine.intent_detection`](../modules/engine/intent_detection.md);
produced by
[`classify_content_intent`](../functions/classify_content_intent.md).

# Values

| Value | Description |
|---|---|
| `DOCS` | Query asks about documentation. |
| `CONFIG` | Query asks about configuration or schema. |
| `NEUTRAL` | No documentation or configuration intent. |
