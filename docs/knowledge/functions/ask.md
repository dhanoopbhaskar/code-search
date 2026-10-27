---
type: Function
title: "ask"
description: "Route question to the surface that can answer it."
resource: code_search/engine/ask.py#ask
tags: [engine, function, ask]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/ask.py
    id: source-code
---

# Overview

Route `question` to the surface that can answer it.

Defined in [`engine.ask`](../modules/engine/ask.md).

# Signature

`def ask(comps: dict[str, Any], question: str, *, limit: int = 10, budget: int = DEFAULT_BUDGET_TOKENS, strict: bool = False, include_tests: bool = False, content: str | None = None) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `comps` | The initialised component registry (`symbol_store`, `edge_store`, `search`, `metadata`, `settings`). |
| `question` | The user's question (natural language, identifier, FQN, or a quoted literal). |
| `limit` | Maximum rows in a callers/callees/implementations/ranked answer. |
| `budget` | Soft output budget in tokens. |
| `strict` | Apply the strict abstention gate to ranked search answers. |
| `include_tests` | Include test files in search answers. |
| `content` | Optional content scope for search answers. |

# Returns

A compact payload with `question`, `answer_type`, `outcome`, `answer`, and `next`. `truncated`/`budget_exceeded` appear when trimming was necessary.
