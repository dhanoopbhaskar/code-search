---
type: Module
title: "engine.symbols"
description: "AST-based symbol extraction and SQLite-backed storage for code symbols: FQNs, call/reference/usage edges, imports, inheritance, visibility, and cached resolution."
resource: code_search/engine/symbols.py
tags: [engine, symbols, ast, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
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
`type_alias`. Groovy has no usable tree-sitter grammar here, so
`_extract_groovy_symbols` recovers types and methods by scanning source text
(`_groovy_block_end` finds the closing brace), and `.groovy`/`.gvy` are
advertised as supported by the parser. `SymbolStore.resolve_name` caches
resolution envelopes per `(query, cap)` and exposes
`invalidate_resolution_cache` for callers that mutate the index; its
`prefer_type=True` flag biases a bare name toward a type declaration when a
class and a member share it.

# Edge Model

Extraction emits more than calls. `_collect_parameter_types` records
`{parameter_name: type_simple_name}` so a receiver's declared type can be
resolved, and the individual emitters add the rest:

| Emitter | Edge | Meaning |
|---|---|---|
| `_emit_call_argument_references` | `CALL_REFERENCE` | A callable passed as an argument |
| `_emit_value_reference` | `CALL_REFERENCE` | A callable used as a value (callback, alias) |
| `_emit_method_reference` | `CALL_REFERENCE` | A Java method reference (`Type::method`) |
| `_emit_usage_reference` | `USAGE` | A conservative member access on a typed receiver |
| `_emit_type_references` | `REFERENCES` | A type name used in an annotation |

`_receiver_is_typed` keeps resolution honest: an untyped local (`x.run()`)
does not produce a resolved edge. `_resolution_via` stores the evidence label
on the edge, `_call_arg_count` records arity so an overload can be chosen, and
`_extract_visibility` classifies visibility for the entry-point and dead-code
rules.

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
