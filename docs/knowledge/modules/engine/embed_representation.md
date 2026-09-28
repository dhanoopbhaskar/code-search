---
type: Module
title: "engine.embed_representation"
description: "Derives deterministic, character-budgeted chunk-embedding input text from a chunk's structural context."
resource: src/engine/embed_representation.py
tags: [engine, embeddings, representation]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embed_representation.py
    id: source-code
---

# Overview

Derives deterministic chunk-embedding input text by composing the
chunk's declaration/body with its nearest enclosing structural context
(module path and declaring-type chain), bounded by a configurable
character budget. Deterministic truncation prioritizes body content over
optional context. Pure functions only — no I/O, model, or database
access; fully unit-testable. Includes `REPRESENTATION_SCHEME_VERSION` to
detect stale embeddings when derivation logic changes.

# Key Constants

`REPRESENTATION_SCHEME_VERSION = 1` — bump when derivation changes to
trigger regeneration of stored embeddings.

# Key Classes

- [`EnclosingContext`](/types/EnclosingContext.md) — a chunk's nearest structural context: module identity, ancestor-name chain, content axis.

# Key Functions

- [`derive_enclosing_context`](/functions/derive_enclosing_context.md) — build the enclosing context for a chunk from its per-file symbol list.
- [`build_embed_text`](/functions/build_embed_text.md) — compose bounded embedding input text (context prefix + body).
