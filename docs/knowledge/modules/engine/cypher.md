---
type: Module
title: "engine.cypher"
description: "Read-only Cypher subset over the SQLite code graph: hand-written lexer, recursive-descent parser, semantic checker, and parameterized SQL compiler with bounded output."
resource: code_search/engine/cypher.py
tags: [engine, graph, cypher, query-language]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

The graph surfaces answer fixed questions (schema, outline, structural search,
dead code, architecture, coverage). This module adds a small, deliberately
strict Cypher reader so an agent can ask multi-hop and aggregate questions
without learning the internal SQLite schema.

The pipeline is lexer → recursive-descent parser → semantic check → parameterized
SQL compiler → bounded executor. Caller text never reaches the SQL: literals
become named parameters, labels and edge types are validated against the stored
vocabulary, and user aliases never appear in the generated statement. The only
dynamic fragments are generated aliases (`n0`, `e1`) and validated property keys
inside `json_extract`.

# Node Mapping

| Cypher label | Source |
|---|---|
| `Function`, `Method`, `Class`, `Interface`, `Enum`, `Constructor`, `Field`, `Variable`, `Import`, `TypeAlias` | `symbols.kind` |
| `File` | synthetic, one per indexed file path |
| `Module` | synthetic, one per distinct directory |
| `Unresolved` | synthetic evidence for an unresolved raw target |

`CONTAINS` edges are synthetic from `symbols.parent_symbol_id`; `IMPORTS` edges
between `File` nodes come from `module_edges`.

# Limits

| Constant | Value | Meaning |
|---|---|---|
| `MAX_ROWS` / `DEFAULT_ROWS` | 500 / 100 | Response row cap |
| `MAX_TIMEOUT_MS` / `DEFAULT_TIMEOUT_MS` | 30000 / 5000 | Progress-handler deadline |
| `MAX_BYTES` | 200000 | Serialized payload ceiling |
| `MAX_QUERY_CHARS` | 20000 | Query text ceiling |
| `MAX_VARIABLE_LENGTH` / `DEFAULT_VARIABLE_LENGTH` | 5 / 3 | Bounded relationship length |
| `MAX_REGEX_CHARS` | 500 | `=~` pattern ceiling |

# Failure Modes

Unsupported syntax raises an error whose message starts with `unsupported`; it
never silently returns an empty result. Write keywords (`CREATE`, `MERGE`,
`DELETE`, `SET`, …) are rejected outright (`_WRITE_KEYWORDS`). Execution errors
and timeouts come back as payloads (`outcome: invalid_argument` / `outcome:
timeout`) rather than exceptions. Absence is not proof of completeness: an empty
result means the current generation has no matching row, not that the code does
not exist.

# Public API

- [`cypher_tokenize`](../../functions/cypher_tokenize.md), [`compile_cypher`](../../functions/compile_cypher.md),
  [`query_digest`](../../functions/query_digest.md),
  [`execute_cypher`](../../functions/execute_cypher.md),
  [`render_cypher_text`](../../functions/render_cypher_text.md).

# Types

The grammar model is documented as grouped concepts:
[`CypherExpressions`](../../types/CypherExpressions.md),
[`CypherPatterns`](../../types/CypherPatterns.md),
[`CypherClauses`](../../types/CypherClauses.md),
[`CompiledQuery`](../../types/CompiledQuery.md),
[`CypherError`](../../types/CypherError.md), and
[`CypherToken`](../../types/CypherToken.md).

# Internal Structure

`_Parser` is the recursive-descent parser; `_Compiler` turns one parsed part into
parameterized SQL; `_Usage`/`_collect_usage` keep the base CTEs small by
restricting them to the labels and edge types a query actually needs;
`_AliasFactory` generates injection-safe aliases; `_Binding`, `_NodeRef`, and
`_PartResult` hold compiler state. `_register_functions` installs the
deterministic SQLite helpers (`cypher_basename`, `cypher_dirname`, `regexp`)
used by the generated SQL, and `_encode_cursor`/`_decode_cursor` implement the
generation-keyed paging cursor.

# Surfaces

`code-search cypher` ([`cmd_cypher`](../../functions/cmd_cypher.md)) and the MCP
`cypher_query` tool.
