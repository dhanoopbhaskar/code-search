---
type: Function
title: "search_symbols"
description: "Search symbols by structure rather than text similarity."
resource: code_search/engine/graph_surface.py#search_symbols
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Search symbols by structure rather than text similarity.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def search_symbols(db: GraphDatabase, *, query: str | None = None, name_pattern: str | None = None, qn_pattern: str | None = None, kind: str | list[str] | None = None, file_pattern: str | None = None, min_degree: int | None = None, max_degree: int | None = None, edge_types: list[str] | None = None, exclude_entry_points: bool = True, include_connected: bool = False, limit: int = 50, offset: int = 0, index_root: Path | None = None) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `query` | Optional case-insensitive substring over name, FQN, and docstring. |
| `name_pattern` | Optional Python regex, matched against the full name. |
| `qn_pattern` | Optional Python regex, matched against the full FQN. |
| `kind` | Optional declaration kind or kinds (`"method"`, `"class,interface"`, `["function"]`). |
| `file_pattern` | Optional glob (or `re:<regex>`) over the file path. |
| `min_degree` | Minimum resolved total degree (incoming + outgoing). |
| `max_degree` | Maximum resolved total degree. |
| `edge_types` | Edge types counted for degree filters; defaults to the stored degree-capable set and ignores unresolved edges. |
| `exclude_entry_points` | Exclude the stored entry-point classification (tests, `main`, constructors, overrides, annotated handlers, and exported top-level declarations). |
| `include_connected` | Attach up to ten resolved neighbours per returned symbol using one batched query. |
| `limit` | Maximum symbols returned (clipped to 200). |
| `offset` | Zero-based offset into the deterministically ordered matches. |
| `index_root` | Indexed repository root, used for relative paths. |

# Returns

A JSON-serialisable payload with `symbols`, exact `total`, paging, echoed filters, and coverage/generation context. An invalid regex returns `outcome: invalid_argument` rather than raising.
