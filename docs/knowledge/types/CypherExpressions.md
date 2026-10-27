---
type: Class
title: "CypherExpressions"
description: "The frozen AST expression nodes of the read-only Cypher subset: literals, variables, property and label tests, function calls, operators, collections, CASE, and EXISTS."
resource: code_search/engine/cypher.py#Expr
tags: [cypher, ast, parser, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

All expression nodes are frozen dataclasses derived from `Expr`, produced by the
recursive-descent `_Parser` and consumed by `_Compiler` (which walks them to emit
parameterized SQL) and `_collect_usage` (which walks them to decide which labels,
edge types, and base CTEs the query needs). Defined in
[`engine.cypher`](../modules/engine/cypher.md).

# Schema

| Node | Fields | Represents |
|---|---|---|
| `Expr` | — | Base class for expression nodes |
| `Literal` | `value` | String, number, boolean, or null literal |
| `Variable` | `name` | A variable reference |
| `Property` | `base: Variable`, `name` | `variable.property` access |
| `LabelTest` | `base: Variable`, `labels` | `variable:Label` predicate |
| `FunctionCall` | `name`, `args`, `distinct`, `star` | Scalar (`_SCALAR_FUNCTIONS`) or aggregate (`_AGGREGATE_FUNCTIONS`) call |
| `BinaryOp` | `op`, `left`, `right` | Binary expression |
| `UnaryOp` | `op`, `operand` | `NOT` or an arithmetic sign |
| `ListLiteral` | `items` | List literal |
| `MapLiteral` | `entries` | Map literal |
| `CaseExpr` | `operand`, `whens`, `default` | Simple or searched `CASE` |
| `ExistsExpr` | `patterns`, `where` | `EXISTS { … }` predicate |

# Notes

`_contains_aggregate(expr)` decides whether a `RETURN`/`WITH` item may appear next
to an aggregate, and `_validate_property_key` checks a `Property.name` before it
is embedded in a `json_extract` path. `Expr` values never carry caller text into
SQL: literal values leave as named parameters.
