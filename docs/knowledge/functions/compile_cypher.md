---
type: Function
title: "compile_cypher"
description: "Parse and compile query to parameterized SQL."
resource: code_search/engine/cypher.py#compile_cypher
tags: [engine, function, cypher]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

Parse and compile `query` to parameterized SQL.

Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Signature

`def compile_cypher(query: str) -> CompiledQuery`

# Parameters

| Name | Description |
|---|---|
| `query` | Cypher query text. |

# Returns

The compiled query. `limit` is the query's own `LIMIT` (`None` when absent), and `skip` is its `SKIP`. The executor adds the response cap and any cursor offset.

# Raises

- CypherError: On syntax, semantic, or unsupported-syntax errors.
