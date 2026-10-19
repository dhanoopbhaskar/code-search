---
type: Function
title: "compact_json"
description: "Serialise a payload to JSON without indentation for compact agent transport."
resource: code_search/engine/graph_query.py#compact_json
tags: [graph, function, serialization]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

`json.dumps` with `separators=(",", ":")` and `default=str`, so non-JSON
values are stringified rather than raising. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def compact_json(payload: dict[str, Any]) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `payload` | `dict[str, Any]` | The payload to serialise. |

# Returns

The minified JSON string.
