---
type: Function
title: "build_embed_text"
description: "Compose bounded embedding input text (context prefix + body)."
resource: src/engine/embed_representation.py#build_embed_text
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embed_representation.py
    id: source-code
---

# Overview

Composes the final, character-budgeted embedding input text by prefixing
a chunk's body with its [`EnclosingContext`](/types/EnclosingContext.md),
truncating deterministically to fit the budget (body content prioritized
over context). Defined in
[`engine.embed_representation`](/modules/engine/embed_representation.md).

# Signature

`def build_embed_text(chunk_body: str, context: EnclosingContext, char_budget: int) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `chunk_body` | `str` | The chunk's declaration/body text. |
| `context` | `EnclosingContext` | The chunk's enclosing structural context. |
| `char_budget` | `int` | Maximum character length of the resulting text. |

# Returns

The composed, bounded embedding input text.
