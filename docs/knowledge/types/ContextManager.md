---
type: Class
title: "ContextManager"
description: "Manages contextual state for the engine's context-assembly layer."
resource: src/context/__init__.py#ContextManager
tags: [context, state]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/context/__init__.py
    id: source-code
---

# Overview

Manages contextual state used by the context-assembly layer, coordinating
retrieval of surrounding code context for search results. Defined in
[`context`](/modules/context/__init__.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, ...) -> None` | Initialize the context manager over its backing stores. |
| `get_context(self, ...) -> dict[str, Any]` | Assemble contextual information for a given chunk or symbol. |
