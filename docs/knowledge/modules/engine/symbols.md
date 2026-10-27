---
type: Module
title: "engine.symbols"
description: "AST-based symbol extraction and SQLite-backed storage for code symbols (FQNs, call/import/inheritance edges) with cached resolution."
resource: code_search/engine/symbols.py
tags: [engine, symbols, ast, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/symbols.py
    id: source-code
---

# Overview

Provides AST-based symbol extraction and SQLite-backed storage for code
symbols. Walks tree-sitter ASTs to discover function/method/class
/interface/enum definitions, their fully-qualified hierarchical names
(FQN), call-graph edges, import relationships, and inheritance edges
across multiple programming languages (Python, Java, JavaScript,
TypeScript, Rust, C++, C#, Go, Kotlin). Symbol FQNs are deduplicated per
file by qualifying collisions with the declaration position, and JS/TS
calls resolve through import bindings and namespace aliases.

Go structs, interfaces, and aliases arrive as `type_spec` nodes, and Kotlin
interfaces parse as `class_declaration`; `_refine_declared_kind` inspects
the declaration's type child or keyword to assign `class`, `interface`, or
`type_alias`. `SymbolStore.resolve_name` caches resolution envelopes per
`(query, cap)` and exposes `invalidate_resolution_cache` for callers that
mutate the index.

# Key Classes

- [`SymbolExtractor`](../../types/SymbolExtractor.md) — extracts symbols and edges (calls, imports, inheritance) from tree-sitter ASTs.
- [`SymbolStore`](../../types/SymbolStore.md) — SQLite-backed CRUD, resolution, and lookup for symbol records.

# Key Functions

- [`build_symbol_fqn`](../../functions/build_symbol_fqn.md) — construct a symbol's fully-qualified name.

# Internal Helpers

`_attach_row_signature` parses a `signature` object onto a database row
from its stored FQN. `_deduplicate_fqns` qualifies colliding symbol FQNs,
and `_build_import_map`/`_build_namespace_map`/`_extract_js_import_edges`
feed JavaScript/TypeScript call resolution.
