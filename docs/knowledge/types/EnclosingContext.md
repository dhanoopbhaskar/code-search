---
type: Class
title: "EnclosingContext"
description: "A chunk's nearest structural context: module identity, ancestor-name chain, content axis."
resource: src/engine/embed_representation.py#EnclosingContext
tags: [embeddings, representation, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embed_representation.py
    id: source-code
---

# Overview

A chunk's nearest structural context — module identity, ancestor-name
chain, and content axis — used to compose bounded embedding input text.
Defined in
[`engine.embed_representation`](/modules/engine/embed_representation.md);
produced by
[`derive_enclosing_context`](/functions/derive_enclosing_context.md) and
consumed by [`build_embed_text`](/functions/build_embed_text.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `module_path` | `str` | Dotted module path of the enclosing file. |
| `ancestor_names` | `list[str]` | Chain of enclosing type/function names, nearest first. |
| `content_type` | `ContentType` | The content axis of the chunk. |
