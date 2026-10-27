---
type: Function
title: "read_index_generation"
description: "Return the current index generation, or `None` for an old index."
resource: code_search/engine/graph_cache.py#read_index_generation
tags: [engine, function, graph_cache]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_cache.py
    id: source-code
---

# Overview

Return the current index generation, or `None` for an old index.

Defined in [`engine.graph_cache`](../modules/engine/graph_cache.md).

# Signature

`def read_index_generation(db: GraphDatabase) -> str | None`
