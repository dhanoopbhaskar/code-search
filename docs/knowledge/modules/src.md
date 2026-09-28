---
type: Module
title: "src"
description: "The code-search package root: an air-gapped, CPU-only AI code context engine."
resource: src/__init__.py
tags: [package, root]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/__init__.py
    id: source-code
---

# Overview

The `src` package is the root of the code-search project: an in-house AI
code context engine for air-gapped, CPU-only enterprise environments. It
provides AST-based indexing, hybrid (BM25 + vector) retrieval,
session-aware reranking, call-graph traversal, and audit-graded
redaction/compliance.

# Subpackages

- [`src.cli`](/modules/cli/__init__.md) — command-line interface
- [`src.engine`](/modules/engine/__init__.md) — core search/index engine
- [`src.mcp`](/modules/mcp/__init__.md) — Model Context Protocol stdio server
- [`src.context`](/modules/context/__init__.md) — on-disk context directory management
