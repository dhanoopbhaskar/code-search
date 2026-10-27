---
type: Class
title: "CypherClauses"
description: "The frozen AST clause nodes of the read-only Cypher subset: MATCH/OPTIONAL MATCH, UNWIND, WITH, RETURN, projections, ordering, and UNION."
resource: code_search/engine/cypher.py#MatchClause
tags: [cypher, ast, parser, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

A parsed statement is a `UnionQuery` of `SingleQuery` clause sequences. Each
clause node is a frozen dataclass that the compiler translates into one SQL
`SELECT`/CTE step. Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Schema

| Node | Fields | Represents |
|---|---|---|
| `MatchClause` | `optional`, `patterns`, `where` | `MATCH` / `OPTIONAL MATCH … WHERE` |
| `UnwindClause` | `expr`, `var` | `UNWIND expr AS var` |
| `Projection` | `expr`, `alias`, `star` | One `RETURN`/`WITH` item, or `*` when `star` is true |
| `OrderItem` | `expr`, `descending` | One `ORDER BY` item |
| `WithClause` | `distinct`, `items`, `where`, `order_by`, `skip`, `limit` | `WITH` |
| `ReturnClause` | `distinct`, `items`, `order_by`, `skip`, `limit` | `RETURN` |
| `SingleQuery` | `clauses` | A linear clause sequence |
| `UnionQuery` | `parts`, `union_all` | One or more single queries combined with `UNION [ALL]` |

# Notes

`_union_order_sql` compiles the union-level `ORDER BY`/`SKIP`/`LIMIT` from the
last `RETURN`, and `_rename_branch_params` prefixes each UNION branch's named
parameters so two branches cannot collide. Row, byte, and deadline caps applied
by [`execute_cypher`](../functions/execute_cypher.md) sit outside the query's own
`SKIP`/`LIMIT`, so a caller cannot lift them by writing a large `LIMIT`.
