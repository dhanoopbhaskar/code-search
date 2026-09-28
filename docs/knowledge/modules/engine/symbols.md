---
type: Module
title: "engine.symbols"
description: "AST-based symbol extraction and SQLite-backed storage for code symbols (FQNs, call/import/inheritance edges)."
resource: src/engine/symbols.py
tags: [engine, symbols, ast, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbols.py
    id: source-code
---

# Overview

Provides AST-based symbol extraction and SQLite-backed storage for code
symbols. Walks tree-sitter ASTs to discover function/method/class
/interface/enum definitions, their fully-qualified hierarchical names
(FQN), call-graph edges, import relationships, and inheritance edges
across multiple programming languages (Python, Java, JavaScript,
TypeScript, Rust, C++, C#).

# Key Classes

- [`SymbolExtractor`](/types/SymbolExtractor.md) — extracts symbols and edges (calls, imports, inheritance) from tree-sitter ASTs.
- [`SymbolStore`](/types/SymbolStore.md) — SQLite-backed CRUD, resolution, and lookup for symbol records.

# Key Functions

- [`build_symbol_fqn`](/functions/build_symbol_fqn.md) — construct a symbol's fully-qualified name.

# Internal Helpers

`_attach_row_signature` parses a `signature` object onto a database row
from its stored FQN.
