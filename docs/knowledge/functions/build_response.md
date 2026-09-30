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
[`IndexChangeDetector`](../types/IndexChangeDetector.md) for a
restart-required notice and, for a code-only scope whose query looks
like config/DDL, deriving a config hint via
[`detect_config_ddl_scent`](detect_config_ddl_scent.md). Defined in
[`engine.response_service`](../modules/engine/response_service.md).

# Signature

`def build_response(results: list[dict[str, Any]], query: str, detector: IndexChangeDetector, content_scope: str = DEFAULT_CONTENT_SCOPE, metadata_store: Any = None, scope_signal: str \| None = None) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `results` | `list[dict[str, Any]]` | Raw search results from the query. |
| `query` | `str` | The user query string. |
| `detector` | `IndexChangeDetector` | Index change detector seeded with the index state the serving process loaded. |
| `content_scope` | `str` | The content-type scope (code, config, docs, all, code_focused). |
| `metadata_store` | `Any` | The `IndexMetadataStore` exposing the current `last_indexed_at`; when `None` the change check is skipped. |
| `scope_signal` | `str \| None` | The engine's surface-neutral scope message, or `None`. |

# Returns

dict with keys: - `results`: The search results. - `envelope`: Index-change envelope or scope message, or None. - `index_status`: Current index status. - `index_changed`: Whether the index changed since the process loaded it. - `reload_required`: Whether a reload is needed. - `silent_empty`: Whether the response hid a silent empty result.
