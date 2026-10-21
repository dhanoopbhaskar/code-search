---
type: Module
title: "engine.response_service"
description: "Search response envelopes: index-change notices, scope hints, compact agent output, and root-relative paths."
resource: code_search/engine/response_service.py
tags: [engine, freshness, response]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
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

# Key Functions

- [`build_response`](../../functions/build_response.md) — build a search response, checking for the index-change envelope and code-scoped config hints.
- [`compact_result`](../../functions/compact_result.md), [`compact_results`](../../functions/compact_results.md) — trimmed, agent-sized result payloads.
- [`relativize_results`](../../functions/relativize_results.md) — rewrite `file_path`/`fqn` relative to the index root.
