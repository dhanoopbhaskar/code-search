---
type: Function
title: "compact_results"
description: "Apply compact_result to every result in a list."
resource: code_search/engine/response_service.py#compact_results
tags: [response, output, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-21T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/response_service.py
    id: source-code
---

# Overview

List-level wrapper around
[`compact_result`](compact_result.md), used by the CLI and daemon to render
agent-sized payloads. Defined in
[`engine.response_service`](../modules/engine/response_service.md).

# Signature

`def compact_results(results: list[dict[str, Any]], max_snippet_lines: int = 20) -> list[dict[str, Any]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `results` | `list[dict[str, Any]]` | Ranked search results. |
| `max_snippet_lines` | `int` | Maximum content lines kept per result. |

# Returns

A list of compacted result dicts.
