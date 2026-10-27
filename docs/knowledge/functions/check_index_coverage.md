---
type: Function
title: "check_index_coverage"
description: "Report where the index has gaps, per requested path or scope."
resource: code_search/engine/graph_surface.py#check_index_coverage
tags: [engine, function, graph_surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

Report where the index has gaps, per requested path or scope.

Defined in [`engine.graph_surface`](../modules/engine/graph_surface.md).

# Signature

`def check_index_coverage(db: GraphDatabase, *, paths: list[str] | None = None, scopes: list[str] | None = None, index_root: Path | None = None, parser: Any | None = None, max_rows: int = _MAX_COVERAGE_ROWS) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to inspect. |
| `paths` | Specific absolute or index-relative file paths. |
| `scopes` | Index-relative directory prefixes to aggregate. |
| `index_root` | Indexed repository root used to resolve relative inputs. |
| `parser` | Optional `ASTParser`, used to classify an unindexed path as excluded or unsupported. |
| `max_rows` | Maximum gap rows or scope entries returned (clipped to 1000). |

# Returns

A JSON-serialisable coverage payload with per-path entries, per-scope aggregates, a summary, and a recommended action.

# Notes

The report distinguishes a clean file from a file that was never indexed:
`no_recorded_issue` means "indexed and no gap was recorded", while
`not_indexed`/`skipped`/`excluded` mean the graph cannot answer for
that path. A clean result is not proof of completeness.
