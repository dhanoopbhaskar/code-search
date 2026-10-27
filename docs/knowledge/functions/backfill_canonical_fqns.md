---
type: Function
title: "backfill_canonical_fqns"
description: "Store `<relative path>::<declaration>` for every symbol."
resource: code_search/engine/graph_passes.py#backfill_canonical_fqns
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Store `<relative path>::<declaration>` for every symbol.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def backfill_canonical_fqns(conn: Any, root_path: Path) -> int`

# Notes

`canonical_fqn` is additive: `fqn` keeps its absolute-path spelling so
every existing query keeps working, while the canonical form is stable
across worktrees and usable for display and later snapshot comparison.
