---
type: Module
title: "engine.response_service"
description: "Response envelope display for index-change notifications and code-scoped config hints."
resource: src/engine/response_service.py
tags: [engine, freshness, response]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/response_service.py
    id: source-code
---

# Overview

Handles response envelope display for index-change notifications and
code-scoped config hints. Detects when the index was rebuilt after the
serving process loaded it and emits a visible "index changed — restart
required" envelope. Falls back to config-hint derivation when the engine
does not supply its own scope signal.

# Key Functions

- [`build_response`](/functions/build_response.md) — build a search response, checking for the index-change envelope and code-scoped config hints.
