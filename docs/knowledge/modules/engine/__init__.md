---
type: Module
title: "src.engine"
description: "The code-search engine: AST-based indexing, hybrid search, reranking, and compliance."
resource: src/engine/__init__.py
tags: [engine, package]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/__init__.py
    id: source-code
---

# Overview

The code-search engine — an AI code context engine for air-gapped
enterprise environments. Provides local, privacy-preserving code search
and navigation through AST-based indexing, hybrid (BM25 + vector)
retrieval, session-aware reranking, and an audit-graded compliance layer.

`VERSION` / `__version__` — currently `"0.1.0"`.

See [engine module index](/modules/engine/index.md) for the full list of
engine submodules.
