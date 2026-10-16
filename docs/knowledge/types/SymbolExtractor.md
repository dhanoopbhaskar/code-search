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
from tree-sitter ASTs. Defined in
[`engine.symbols`](../modules/engine/symbols.md).

# Methods

| Method | Description |
|---|---|
| `__init__(parser: ASTParser) -> None` | Initialize the extractor with the parser used to build ASTs. |
| `extract_symbols(file_path: Path, source_bytes: bytes) -> list[dict[str, Any]]` | Return all symbol definitions found in *file_path*. |
| `extract_edges(file_path: Path, source_bytes: bytes, symbol_catalog: dict[str, int] \| None = None) -> list[dict[str, Any]]` | Extract call, import, and inheritance edges from *file_path*. |
