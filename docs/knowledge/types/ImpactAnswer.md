---
type: Class
title: "ImpactAnswer"
description: "Symbols and files impacted by a set of changed files, with production/test buckets, per-symbol risk labels, and traversal provenance."
resource: code_search/engine/graph_query.py#ImpactAnswer
tags: [graph, query, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
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
| `test_symbols` | `list[GraphNode]` | Impacted symbols living in test files. |
| `production_symbols` | `list[GraphNode]` | Impacted symbols living outside test files. |
| `risks` | `dict[str, str]` | Per-symbol risk label keyed by FQN: `high`, `medium`, or `low`. |
| `risk_summary` | `dict[str, int]` | Count of impacted symbols per risk level (`high`, `medium`, `low`). |
| `parents` | `dict[str, dict[str, str]]` | Traversal provenance: for each impacted node key, the `parent` key it was reached from and the edge `relation`. |
| `direction` | `str` | The traversal direction actually used: `inbound` (default), `outbound`, or `both`. |
| `via` | `list[str]` | Sorted symbol edge types traversed, for example `["CALLS", "INHERITS"]`. |
| `fixpoint` | `bool` | Whether the walk ran to closure instead of stopping at `depth`. |
| `truncated` | `bool` | Whether the `max_nodes` cap cut the impact set short. |
| `summary` | `dict[str, int]` | Counts: `symbols`, `files`, `production_files`, `test_files`, `production_symbols`, `test_symbols`, `tests`, `changed_files`, `high_risk`, `medium_risk`, and `low_risk`, plus the `adjacency` source (`cache` or `sql`). |

# Risk Labels

`risk_summary` is a conservative heuristic, not a contract: a symbol in a
test file is `low`; a type boundary or a symbol with fan-in of at least five
is `high`; fan-in of at least one is `medium`; otherwise `low`.

# Methods

| Method | Description |
|---|---|
| `as_dict() -> dict[str, Any]` | Return the structured impact payload. |
