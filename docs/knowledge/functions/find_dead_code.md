---
type: Function
title: "find_dead_code"
description: "Report callables with no proven incoming reference from production code."
resource: code_search/engine/graph_surface.py#find_dead_code
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Report callables with no proven incoming reference from production code.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def find_dead_code(db: GraphDatabase, *, kinds: str | list[str] | None = None, include_entry_points: bool = False, include_tests: bool = False, limit: int = 50, offset: int = 0, index_root: Path | None = None) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `kinds` | Optional candidate kinds (defaults to function/method/constructor). |
| `include_entry_points` | Include symbols classified as entry points. |
| `include_tests` | Include test symbols as candidates. |
| `limit` | Maximum candidates returned (clipped to 200). |
| `offset` | Zero-based offset into the ordered candidates. |
| `index_root` | Indexed repository root, used for relative paths. |

# Returns

A JSON-serialisable payload with `candidates`, exact `total`, paging, the edge types checked, and a coverage caveat.

# Notes

Candidates are functions, methods, and constructors with no resolved
incoming `CALLS`/`USAGE`/`CALL_REFERENCE`/`REFERENCES`/
`IMPLEMENTS`/`INHERITS` edge from a non-test symbol. Entry points and
test symbols are excluded by default. The result is evidence, never a
deletion recommendation: unresolved same-name references and test-only
usage are reported per row because they are exactly the cases where a
dynamic or external caller could keep the symbol alive.
