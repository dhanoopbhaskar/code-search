---
type: Class
title: "ImpactAnswer"
description: "Symbols and files impacted by a set of changed files."
resource: code_search/engine/graph_query.py#ImpactAnswer
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Returned by [`GraphQueryService.impact`](GraphQueryService.md) and consumed by
[`cmd_affected`](../functions/cmd_affected.md). Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `changed_paths` | `list[str]` | The changed files supplied by the caller. |
| `symbols` | `list[GraphNode]` | Symbols declared in the changed files. |
| `impacted` | `list[GraphNode]` | Symbols reverse-reachable from the changed symbols. |
| `files` | `list[str]` | Files containing impacted symbols or importing a changed file. |
| `production_files` | `list[str]` | The impacted files classified as production code. |
| `test_files` | `list[str]` | The impacted files classified as test code. |
| `summary` | `dict[str, int]` | Counts: `symbols`, `files`, `tests`, and `changed_files`. |

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return the structured impact payload. |
