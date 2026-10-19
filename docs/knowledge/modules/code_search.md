---
type: Module
title: "code_search"
description: "The code-search package root: an air-gapped, CPU-only AI code context engine."
resource: code_search/__init__.py
tags: [package, root]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/__init__.py
    id: source-code
---

# Overview

The `code_search` package is the root of the code-search project: an AI
code context engine for air-gapped, CPU-only enterprise environments. It
provides AST-based indexing, hybrid (BM25 + vector) retrieval,
session-aware reranking, call-graph traversal, and audit-graded
redaction/compliance.

# Subpackages

- [`code_search.cli`](cli/__init__.md) — command-line interface
- [`code_search.engine`](engine/__init__.md) — core search/index engine
- [`code_search.mcp`](mcp/__init__.md) — Model Context Protocol stdio server
- [`code_search.context`](context/__init__.md) — on-disk context directory management
