---
type: Function
title: "build_response"
description: "Build a search response, checking for the index-change envelope and code-scoped config hints."
resource: src/engine/response_service.py#build_response
tags: [freshness, response, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/response_service.py
    id: source-code
---

# Overview

Builds the final search response envelope, checking
[`IndexChangeDetector`](/types/IndexChangeDetector.md) for a
restart-required notice and falling back to config-hint derivation via
[`build_scope_signal`](/functions/build_scope_signal.md) when the engine
supplies no scope signal of its own. Defined in
[`engine.response_service`](/modules/engine/response_service.md).

# Signature

`def build_response(search_result: dict[str, Any], change_detector: IndexChangeDetector) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `search_result` | `dict[str, Any]` | The raw result envelope from [`HybridSearch.search`](/types/HybridSearch.md). |
| `change_detector` | `IndexChangeDetector` | Detector used to check for index changes since load. |

# Returns

The final response envelope, possibly augmented with a restart notice or scope hint.
