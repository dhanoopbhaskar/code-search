---
type: Function
title: "display_symbol"
description: "Return an FQN with its filesystem path prefix removed for display."
resource: code_search/engine/graph_query.py#display_symbol
tags: [graph, output, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-21T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Stored FQNs are `<absolute file path>::<declaration>`. The path prefix is
noise in text output, so it is dropped while logical module prefixes (for
example `pkg.module::Thing`) are preserved: the prefix is stripped only when
it contains a path separator. A `file:` scheme prefix is removed. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def display_symbol(fqn: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `fqn` | `str` | A stored fully-qualified symbol name. |

# Returns

The FQN without any filesystem path prefix.
