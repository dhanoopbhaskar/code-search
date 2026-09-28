---
type: Module
title: "engine.implementations"
description: "Interface implementation lookup — the single shared resolution/traversal rule for get_implementations."
resource: src/engine/implementations.py
tags: [engine, graph, implementations]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/implementations.py
    id: source-code
---

# Overview

Interface implementation lookup — the one shared resolution/traversal
rule. Resolves a reference to an interface/type member, walks the
`INHERITS` graph backwards to every static subtype, matches the member by
name and normalized signature, and classifies into one of four outcomes:
`resolved`, `ambiguous`, `not_found`, `no_static_implementation`. Every
retrieval surface (MCP tool, CLI, daemon, traversal) delegates here, so
candidates, classification, and ordering never diverge. Performs no I/O
beyond the symbol and edge stores.

# Key Functions

- [`find_implementations`](/functions/find_implementations.md) — resolve static implementations of an interface member or type.
