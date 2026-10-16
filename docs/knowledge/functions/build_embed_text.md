---
type: Function
title: "build_embed_text"
description: "Compose bounded embedding input text (context prefix + body)."
resource: code_search/engine/embed_representation.py#build_embed_text
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/embed_representation.py
    id: source-code
---

# Overview

Composes the final, character-budgeted embedding input text by prefixing
a chunk's body with its [`EnclosingContext`](../types/EnclosingContext.md),
truncating deterministically to fit the budget (body content prioritized
over context). Defined in
[`engine.embed_representation`](../modules/engine/embed_representation.md).

# Signature

`def build_embed_text(context: EnclosingContext \| None, content: str, budget: int) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context` | `EnclosingContext \| None` | The chunk's enclosing context, or `None` when unavailable. |
| `content` | `str` | The chunk body (declaration + body), never mutated. |
| `budget` | `int` | Maximum characters of the returned text (floored at `1`). |

# Returns

The text to embed for the chunk.
