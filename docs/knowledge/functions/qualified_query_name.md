---
type: Function
title: "qualified_query_name"
description: "Extract the qualified name portion of a query, if any."
resource: src/engine/confidence.py#qualified_query_name
tags: [confidence, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Extracts the qualified-name portion of a query string, used by the
exact-match evidence classifiers. Defined in
[`engine.confidence`](/modules/engine/confidence.md).

# Signature

`def qualified_query_name(query: str) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The qualified name substring, or `None` if the query has no such pattern.
