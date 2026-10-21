---
type: Function
title: "find_implementations"
description: "Resolve static implementations of an interface member or type."
resource: code_search/engine/implementations.py#find_implementations
tags: [implementations, graph, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/implementations.py
    id: source-code
---

# Overview

Resolves static implementations of an interface member or type by
walking the inheritance (`INHERITS`) graph. When no static implementer exists,
the envelope may carry a `framework` descriptor (for example Spring Data
repositories, `@FeignClient`, `@Mapper`, `@RepositoryRestResource`) explaining
that the implementation is generated at runtime by convention, rather than
leaving the caller to infer why. Defined in
[`engine.implementations`](../modules/engine/implementations.md).

# Signature

`def find_implementations(symbol_store: SymbolStore, edge_store: EdgeStore, reference: str, max_depth: int \| None = None) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `symbol_store` | `SymbolStore` | The symbol store used to resolve the reference and read member declarations. |
| `edge_store` | `EdgeStore` | The edge store used for the reverse (subtype) and forward (ancestor) `INHERITS` walks. |
| `reference` | `str` | An FQN, conventional FQN, partial, or bare member name. |
| `max_depth` | `int \| None` | Optional reverse-traversal bound; defaults to `max_graph_depth` so indirect (sub-interface) implementations are reached like every other surface. |

# Returns

The shared `ImplementationResult` envelope: `outcome`, `symbol`,
`declaring_type`, `implementations`, `candidates`, `framework`, and
`explanation`. The framework descriptor carries `name`, `generated`, `bases`,
and `note`, or is `None` when no framework signal is present.
