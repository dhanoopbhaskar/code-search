---
type: Function
title: "rebuild_derived_graph_data"
description: "Recompute canonical FQNs, TESTS edges, entry points, importance, degrees."
resource: code_search/engine/graph_passes.py#rebuild_derived_graph_data
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Recompute canonical FQNs, TESTS edges, entry points, importance, degrees.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def rebuild_derived_graph_data(db: Any, root_path: Path, settings: Settings | None = None) -> dict[str, int]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to update. |
| `root_path` | Indexed repository root, used for project-relative names. |
| `settings` | Engine settings (configured entry-point patterns). |

# Returns

A deterministic summary `{symbols, tests_edges, entry_points, degrees_rows}`.
