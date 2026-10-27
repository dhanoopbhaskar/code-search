---
type: Function
title: "execute_cypher"
description: "Execute a read-only Cypher query with bounded output and a deadline."
resource: code_search/engine/cypher.py#execute_cypher
tags: [engine, function, cypher]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

Execute a read-only Cypher query with bounded output and a deadline.

Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Signature

`def execute_cypher(db: GraphDatabase, query: str, *, limit: int = DEFAULT_ROWS, offset: int = 0, cursor: str = '', timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]`

# Parameters

| Name | Description |
|---|---|
| `db` | The graph database to query. |
| `query` | Cypher query text. |
| `limit` | Maximum rows returned in one response (clipped to 500). |
| `offset` | Zero-based row offset. Ignored when `cursor` is set. |
| `cursor` | A cursor from the previous page. It is valid only for the same index generation and query text. |
| `timeout_ms` | Wall-clock deadline in milliseconds (clipped to 1..30000). |

# Returns

A JSON-serialisable payload with columns, rows, paging, generation, digest, timing, and a trust note. Errors are returned as `outcome: invalid_argument` (`error_kind`/`error`) or `outcome: timeout` rather than raised.
