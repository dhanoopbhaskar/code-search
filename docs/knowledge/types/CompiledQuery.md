---
type: Class
title: "CompiledQuery"
description: "A parsed Cypher query compiled to parameterized SQL, with its column names and paging bounds, ready for the executor."
resource: code_search/engine/cypher.py#CompiledQuery
tags: [cypher, compiler, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

The output of [`compile_cypher`](../functions/compile_cypher.md) and the input of
[`execute_cypher`](../functions/execute_cypher.md). Defined in
[`engine.cypher`](../modules/engine/cypher.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `sql` | `str` | Parameterized SQLite statement; caller text never appears in it |
| `params` | `dict[str, Any]` | Named bind parameters, including per-UNION-branch renamed keys |
| `columns` | `list[str]` | Result column names in `RETURN` order |
| `skip` | `int` | The query's own `SKIP` |
| `limit` | `int \| None` | The query's own `LIMIT`, or `None` when absent (the executor then applies its response cap) |
| `timeout_ms` | `int` | Deadline carried into execution (default `DEFAULT_TIMEOUT_MS` = 5000) |
| `order_items` | `tuple[OrderItem, ...]` | Union-level ordering, kept for cursor stability |

# Guarantees

Compilation is deterministic: the same query text yields the same SQL, the same
parameter names, and the same `columns`. That stability is what lets
[`query_digest`](../functions/query_digest.md) key a paging cursor on the query
text and the generation.
