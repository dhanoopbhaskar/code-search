---
type: Function
title: "find_implementations"
description: "Resolve static implementations of an interface member or type."
resource: src/engine/implementations.py#find_implementations
tags: [implementations, graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/implementations.py
    id: source-code
---

# Overview

Resolves static implementations of an interface member or type using the
call/inheritance graph. Defined in
[`engine.implementations`](/modules/engine/implementations.md).

# Signature

`def find_implementations(edge_store: EdgeStore, fqn: str, kind: str = "subtypes") -> list[dict[str, Any]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `edge_store` | `EdgeStore` | Graph edge store to query. |
| `fqn` | `str` | Fully-qualified name of the interface/type/member. |
| `kind` | `str` | `"subtypes"` or `"ancestors"`. |

# Returns

List of implementation records.
