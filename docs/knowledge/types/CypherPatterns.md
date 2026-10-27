---
type: Class
title: "CypherPatterns"
description: "The frozen AST pattern nodes of the read-only Cypher subset: node patterns, relationship patterns with direction and length, and node/relationship paths."
resource: code_search/engine/cypher.py#NodePattern
tags: [cypher, ast, parser, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

Pattern nodes describe what the compiler joins: a labelled node, a typed and
directed relationship of bounded length, and the path that ties them together.
Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Schema

| Node | Fields | Represents |
|---|---|---|
| `NodePattern` | `var`, `labels`, `props` | `(var:Label {props})` |
| `RelPattern` | `var`, `types`, `direction` (`out`/`in`/`both`), `length: (min, max)`, `props` | A relationship pattern with direction and optional length |
| `PathPattern` | `nodes`, `rels` | A node/relationship path |

# Constraints

Relationship length is bounded by `DEFAULT_VARIABLE_LENGTH` (3) and
`MAX_VARIABLE_LENGTH` (5), which keeps the generated recursive CTEs cheap and
prevents an unbounded walk from a single query. Labels and relationship types are
validated against the stored vocabulary during semantic checking, so an unknown
label fails the query instead of silently matching nothing.
