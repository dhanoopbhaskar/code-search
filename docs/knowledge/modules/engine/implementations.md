---
type: Module
title: "engine.implementations"
description: "Interface implementation lookup — the single shared resolution/traversal rule for get_implementations."
resource: code_search/engine/implementations.py
tags: [engine, graph, implementations]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/implementations.py
    id: source-code
---

# Overview

Interface implementation lookup — the one shared resolution/traversal
rule. Resolves a reference to an interface/type member, walks the
`INHERITS` graph backwards to every static subtype (including indirect
sub-interfaces), matches the member by name and normalized signature, and
classifies into one of four outcomes: `resolved`, `ambiguous`, `not_found`,
`no_static_implementation`. Each implementation carries its
`relationship` (`direct` for depth 1, `indirect` beyond) and the inherited
declaration site when the member is provided by an ancestor. Every
retrieval surface (MCP tool, CLI, daemon, traversal) delegates here, so
candidates, classification, and ordering never diverge. Performs no I/O
beyond the symbol and edge stores.

# Key Functions

- [`find_implementations`](../../functions/find_implementations.md) — resolve static implementations of an interface member or type.
