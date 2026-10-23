---
type: Module
title: "engine.response_service"
description: "Search response envelopes: index-change notices, scope hints, compact agent output (including paths-only), and root-relative paths."
resource: code_search/engine/response_service.py
tags: [engine, freshness, response]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/response_service.py
    id: source-code
---

# Overview

Handles response envelope display for index-change notifications and
code-scoped config hints. Detects when the index was rebuilt after the
serving process loaded it and emits a visible "index changed — restart
required" envelope. Falls back to config-hint derivation when the engine
does not supply its own scope signal. Also provides the agent-facing output
shaping shared by the CLI and daemon: compacting results and rewriting
paths/FQNs relative to the index root.

Compact output shortens `fqn` to the trailing symbol name and omits empty
optional fields. `max_snippet_lines=0` returns no content (matching the MCP
contract), and `paths_only=True` returns only location and classification
fields for path-oriented queries. The default snippet budget is 10 lines.

# Key Functions

- [`build_response`](../../functions/build_response.md) — build a search response, checking for the index-change envelope and code-scoped config hints.
- [`compact_result`](../../functions/compact_result.md), [`compact_results`](../../functions/compact_results.md) — trimmed, agent-sized result payloads with `paths_only` and no-content support.
- [`relativize_results`](../../functions/relativize_results.md) — rewrite `file_path`/`fqn` relative to the index root.
