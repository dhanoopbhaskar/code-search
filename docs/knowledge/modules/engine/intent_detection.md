---
type: Module
title: "engine.intent_detection"
description: "Lexical query-intent classification (docs/config/neutral) and scope-signal message generation."
resource: src/engine/intent_detection.py
tags: [engine, query-analysis, intent]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/intent_detection.py
    id: source-code
---

# Overview

Lexical query-intent classification into documentation, configuration, or
neutral, plus scope-signal message generation. Classification is pure,
deterministic, and air-gap safe — no I/O, corpus scan, or network. Used
to detect user intent from query text and explain scope behavior (e.g.,
why documentation was excluded) in search response envelopes.

# Key Classes

- [`ContentIntent`](/types/ContentIntent.md) — `StrEnum` for the content axis a query targets (`DOCS`, `CONFIG`, `NEUTRAL`).

# Key Functions

- [`classify_content_intent`](/functions/classify_content_intent.md) — classify a query lexically into docs/config/neutral.
- [`scope_override`](/functions/scope_override.md) — the neutral scope token that would include the intent's content type.
- [`build_scope_signal`](/functions/build_scope_signal.md) — generate a surface-neutral scope message explaining an exclusion.
