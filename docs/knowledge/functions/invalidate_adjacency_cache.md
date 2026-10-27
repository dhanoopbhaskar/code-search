---
type: Function
title: "invalidate_adjacency_cache"
description: "Drop cached snapshots for db_path after a committed graph write."
resource: code_search/engine/graph_cache.py#invalidate_adjacency_cache
tags: [engine, function, graph_cache]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

Drop cached snapshots for `db_path` after a committed graph write.

Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md).

# Signature

`def invalidate_adjacency_cache(db_path: str | Path) -> None`
