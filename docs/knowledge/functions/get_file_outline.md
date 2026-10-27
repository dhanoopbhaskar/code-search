---
type: Function
title: "get_file_outline"
description: "Return the declarations of one indexed file in source order."
resource: code_search/engine/graph_surface.py#get_file_outline
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Return the declarations of one indexed file in source order.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def get_file_outline(db: GraphDatabase, file_path: str, *, index_root: Path | None = None, kinds: list[str] | None = None, limit: int = 200, offset: int = 0, include_docstring: bool = False, include_ids: bool = False) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `file_path` | Absolute or index-relative path to the file. |
| `index_root` | Indexed repository root used to resolve a relative path. |
| `kinds` | Optional declaration-kind filter. |
| `limit` | Maximum declarations to return (clipped to 500). |
| `offset` | Zero-based offset into the source-ordered declaration list. |
| `include_docstring` | Include the stored docstring (off by default to save response tokens). |
| `include_ids` | Include full FQNs, conventional FQNs, absolute columns, and `parent_fqn`. The default compact row keeps the short `parent_name` and relative line range only. |

# Returns

A JSON-serialisable outline with the resolved path, declarations, exact total, and truncation flag. `outcome` is `not_indexed` when no declaration for the file exists in the index.
