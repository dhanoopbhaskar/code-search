---
type: Function
title: "derive_interface_dispatch_edges"
description: "Add resolved `CALLS` edges from an interface call site to its impls."
resource: code_search/engine/graph_passes.py#derive_interface_dispatch_edges
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Add resolved `CALLS` edges from an interface call site to its impls.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def derive_interface_dispatch_edges(db: Any) -> int`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to update. |

# Returns

The number of derived `CALLS` edges inserted.

# Notes

A receiver declared with an interface type (`provider.handle()`) resolves
to the interface method, so a path or impact walk never reaches the class
that actually handles the call. This pass closes that gap: for every
resolved `CALLS` edge whose target is a method declared on an interface,
it adds one edge per implementing/subclass method with the same name and a
compatible arity. Edges are marked `properties.via =
"interface_dispatch"` and tiered `type_infer` so consumers can tell a
derived dispatch edge from a directly resolved call.

The pass is deterministic and idempotent: prior dispatch edges are deleted
before the rebuild, and insertion uses `INSERT OR IGNORE` so an existing
direct edge to the implementation wins.
