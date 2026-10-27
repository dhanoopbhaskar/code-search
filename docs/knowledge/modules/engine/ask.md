---
type: Module
title: "engine.ask"
description: "Single-question router that maps a natural-language question to the retrieval surface that can answer it and returns one compact, budgeted answer."
resource: code_search/engine/ask.py
tags: [engine, ask, routing, agent-surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/ask.py
    id: source-code
---

# Overview

`ask` replaces "pick one of fifteen commands" with one entry point: a question
is routed to the surface that can answer it and the answer comes back already
shaped for an agent — compact rows, inline source capped at
`DEFAULT_BUDGET_TOKENS` (1200 tokens), and `next` suggestions for follow-up
commands.

The router delegates every answer to the shared engine rule
(`SymbolStore.resolve_name`, `EdgeStore.get_call_graph_page`,
[`find_implementations`](../../functions/find_implementations.md),
[`HybridSearch.search`](../../types/HybridSearch.md)), so an `ask` response
cannot disagree with the dedicated surface for the same request.

# Routing

`_route(question)` returns `(intent, target)` and applies the rules in order:

| Order | Rule | Intent |
|---|---|---|
| 1 | A quoted literal (`` `foo` ``/`"foo"`/`'foo'`) | `literal` → exhaustive search |
| 2 | `who calls X`, `callers of X`, `who invokes X` | `callers` |
| 3 | `what does X call`, `callees of X`, `dependencies of X` | `callees` |
| 4 | `who implements X`, `implementations of X` | `implementations` |
| 5 | `where is X defined`, `definition of X`, `what is X` | `definition` |
| 6 | Question text that is identifier-shaped | `definition` |
| 7 | Anything else | `ranked` (hybrid search) |

A quoted literal wins over phrase routing because the quotes are an explicit
request for exact text. `_clean_target` strips surrounding quotes and trailing
punctuation before resolution.

# Answer Contract

Every payload carries `question`, `answer_type`, `outcome`, `answer`, and
`next`; `truncated` and `budget_exceeded` appear only when a soft budget forced
trimming. A failed symbol resolution returns `candidates` plus `suggestion`
rather than an empty success, so "not found" and "ambiguous" stay
distinguishable from "no search hits".

# Internal Helpers

`_symbol_summary` compacts a resolved symbol (identity, location, signature,
docstring, and the first `_DEFINITION_LINES` = 40 source lines, redacted when a
redactor is configured). `_relativize_payload` strips the index root from every
path-like field, `_fit_budget` trims list rows and inline source until the
payload fits, and `_payload_size`/`_next_steps` measure and annotate the
result. `_search_answer` reuses the ranked or exhaustive search path,
`_call_graph_answer`/`_definition_answer`/`_implementations_answer` reuse the
graph and resolution rules.

# Public API

- [`ask`](../../functions/ask.md) — route and answer one question.

# Surfaces

`code-search ask` ([`cmd_ask`](../../functions/cmd_ask.md)) and the MCP `ask`
tool.
