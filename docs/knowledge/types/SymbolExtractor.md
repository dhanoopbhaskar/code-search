---
type: Class
title: "SymbolExtractor"
description: "Extracts symbols and edges (calls, imports, inheritance) from tree-sitter ASTs."
resource: code_search/engine/symbols.py#SymbolExtractor
tags: [symbols, ast]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/symbols.py
    id: source-code
---

# Overview

Extracts symbols (definitions) and edges (calls, imports, inheritance)
from tree-sitter ASTs. Symbol FQNs are made unique per file: colliding
FQNs are qualified with the declaration line and column so a re-declared
helper is not silently dropped. TypeScript/JavaScript calls are resolved
through the file's import bindings and namespace aliases. Defined in
[`engine.symbols`](../modules/engine/symbols.md).

# Methods

| Method | Description |
|---|---|
| `__init__(parser: ASTParser) -> None` | Initialize the extractor with the parser used to build ASTs. |
| `extract_symbols(file_path: Path, source_bytes: bytes) -> list[dict[str, Any]]` | Return all symbol definitions found in *file_path*. |
| `extract_edges(file_path: Path, source_bytes: bytes, symbol_catalog: dict[str, int] \| None = None) -> list[dict[str, Any]]` | Extract call, import, and inheritance edges from *file_path*. |
| `_deduplicate_fqns(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]` | Qualify colliding FQNs with `@<line>:<column>` so every extracted symbol stays addressable. |
| `_build_import_map(import_edges: list[dict[str, Any]]) -> dict[str, str]` | Map local import bindings to their qualified targets for call resolution. |
| `_build_namespace_map(import_edges: list[dict[str, Any]]) -> dict[str, str]` | Map namespace aliases (for example `import * as x`) to their module targets. |
| `_extract_js_import_edges(text: str, current_fqn: str \| None, source_range: str, edges: list[dict[str, Any]]) -> None` | Parse JS/TS import/require clauses into raw import edges. |
