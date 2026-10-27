---
type: Class
title: "CypherError"
description: "Parse, semantic, or execution error carrying an agent-facing message for the read-only Cypher subset."
resource: code_search/engine/cypher.py#CypherError
tags: [cypher, error, types]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/cypher.py
    id: source-code
---

# Overview

The single exception type raised while lexing, parsing, checking, or compiling a
Cypher query. Defined in [`engine.cypher`](../modules/engine/cypher.md).

# Contract

| Property | Behaviour |
|---|---|
| Inherits | `Exception` |
| Message | Human- and agent-readable; unsupported syntax starts with `unsupported` |
| Severity | Fatal for the query — the caller never receives a partial result |

# Consumers

[`compile_cypher`](../functions/compile_cypher.md) raises it;
[`execute_cypher`](../functions/execute_cypher.md) catches it and converts it
into an `outcome: invalid_argument` payload with `error_kind` and `error`
fields, so MCP and CLI callers see an error object instead of a traceback.
