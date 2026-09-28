---
type: Module
title: "engine.symbol_resolution"
description: "Deterministic, database-free symbol reference parsing and disambiguation policy."
resource: src/engine/symbol_resolution.py
tags: [engine, symbols, resolution]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbol_resolution.py
    id: source-code
---

# Overview

Deterministic, database-free symbol reference parsing and disambiguation
policy. Holds pure functions for resolving name queries against indexed
candidates, outcome mapping, and evidence-based ranking. Has no
dependency on [`symbols.py`](/modules/engine/symbols.md) or
[`graph.py`](/modules/engine/graph.md), enabling both to import it
without circular dependencies. Every function is deterministic: identical
query + index state yields byte-for-byte identical results.

# Key Constants

`OUTCOME_RESOLVED`, `OUTCOME_AMBIGUOUS`, `OUTCOME_NOT_FOUND` — user-visible
resolution outcomes. `EVIDENCE_EXACT_FQN`, `EVIDENCE_PARENT_SCOPE_MATCH`,
`EVIDENCE_SIGNATURE_MATCH`, etc. — ranking signal tokens.

# Key Classes

- [`SymbolReference`](/types/SymbolReference.md) — a parsed caller-supplied name broken into matching components.
- [`ResolutionResult`](/types/ResolutionResult.md) — the policy decision for one reference.

# Key Functions

- [`outcome_for_kind`](/functions/outcome_for_kind.md) — map an envelope `kind` to a user-visible outcome.
- [`is_deprecated`](/functions/is_deprecated.md) — whether `declared_rules` carries a deprecation marker.
- [`normalize_signature`](/functions/normalize_signature.md) — parse and normalize a `(params)` signature.
- [`strip_params`](/functions/strip_params.md), [`symbol_leaf`](/functions/symbol_leaf.md) — name-shape helpers.
- [`parse_reference`](/functions/parse_reference.md) — parse a query into a `SymbolReference`.
- [`resolve_reference`](/functions/resolve_reference.md) — apply resolution tiers to rank candidates.
- [`resolve_with_signature`](/functions/resolve_with_signature.md) — signature-aware overload disambiguation.
