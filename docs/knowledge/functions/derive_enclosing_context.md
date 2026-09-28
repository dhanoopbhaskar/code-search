---
type: Function
title: "derive_enclosing_context"
description: "Build the enclosing context for a chunk from its per-file symbol list."
resource: src/engine/embed_representation.py#derive_enclosing_context
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embed_representation.py
    id: source-code
---

# Overview

Builds an [`EnclosingContext`](/types/EnclosingContext.md) for a chunk
from its per-file symbol list, resolving the module path, ancestor chain,
and content axis. Defined in
[`engine.embed_representation`](/modules/engine/embed_representation.md).

# Signature

`def derive_enclosing_context(chunk: dict[str, Any], file_symbols: list[dict[str, Any]]) -> EnclosingContext`

# Parameters

| Name | Type | Description |
|---|---|---|
| `chunk` | `dict[str, Any]` | The chunk to derive context for. |
| `file_symbols` | `list[dict[str, Any]]` | All symbols declared in the chunk's file. |

# Returns

The derived [`EnclosingContext`](/types/EnclosingContext.md).
