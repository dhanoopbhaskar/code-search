---
type: Function
title: "exact_precheck"
description: "Detect concrete literal/annotation/identifier patterns in a query."
resource: src/engine/search.py#exact_precheck
tags: [search, query-analysis, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

Detects concrete literal, annotation, or identifier patterns in a query
(e.g. quoted strings, `@Annotation`) that warrant an exact-match search
path ahead of the general hybrid pipeline. Defined in
[`engine.search`](/modules/engine/search.md).

# Signature

`def exact_precheck(query: str) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `query` | `str` | The raw query text. |

# Returns

The detected literal pattern, or `None` if none found.
