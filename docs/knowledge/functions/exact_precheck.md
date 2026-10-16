---
type: Function
title: "exact_precheck"
description: "Detect concrete literal/annotation/identifier patterns in a query."
resource: code_search/engine/search.py#exact_precheck
tags: [search, query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

Detects concrete literal, annotation, or identifier patterns in a query
(e.g. quoted strings, `@Annotation`) that warrant an exact-match search
path ahead of the general hybrid pipeline. Defined in
[`engine.search`](../modules/engine/search.md).

# Signature

`def exact_precheck(query: str) -> dict[str, Any] \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

A descriptor dict with `annotations`, `quotes`, `literals`, and `identifier`
keys when the query triggers the exact-match arm, or `None` for plain prose
(no concrete token form).
