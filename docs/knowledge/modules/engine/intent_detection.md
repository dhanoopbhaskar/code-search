---
type: Module
title: "engine.intent_detection"
description: "Lexical query-intent classification (docs/config/code/neutral) and scope-signal message generation."
resource: code_search/engine/intent_detection.py
tags: [engine, query-analysis, intent]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/intent_detection.py
    id: source-code
---

# Overview

Lexical query-intent classification into documentation, configuration,
code, or neutral, plus scope-signal message generation. Classification is
pure, deterministic, and air-gap safe — no I/O, corpus scan, or network.
Precedence is docs → config → code → neutral. Used to infer the default
content scope (a code-shaped query defaults to `code`, a docs-shaped query
is widened to `all`, others use `code_focused`) and to explain scope
behavior (e.g., why documentation was excluded) in search response
envelopes.

# Key Classes

- [`ContentIntent`](../../types/ContentIntent.md) — `StrEnum` for the content axis a query targets (`DOCS`, `CONFIG`, `CODE`, `NEUTRAL`).

# Key Functions

- [`classify_content_intent`](../../functions/classify_content_intent.md) — classify a query lexically into docs/config/code/neutral.
- [`scope_override`](../../functions/scope_override.md) — the neutral scope token that would include the intent's content type.
- [`build_scope_signal`](../../functions/build_scope_signal.md) — generate a surface-neutral scope message explaining an exclusion.
