---
type: Class
title: "SymbolExtractor"
description: "Extracts symbols and edges (calls, imports, inheritance) from tree-sitter ASTs."
resource: src/engine/symbols.py#SymbolExtractor
tags: [symbols, ast]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbols.py
    id: source-code
---

# Overview

Extracts symbols (definitions) and edges (calls, imports, inheritance)
from tree-sitter ASTs. Defined in
[`engine.symbols`](/modules/engine/symbols.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, parser: ASTParser) -> None` | Initialize extractor with an AST parser. |
| `extract_symbols(self, file_path: Path, source_bytes: bytes) -> list[dict[str, Any]]` | Extract all symbol definitions from a source file. |
| `extract_edges(self, file_path: Path, source_bytes: bytes, symbol_catalog: dict[str, int] \| None = None) -> list[dict[str, Any]]` | Extract call, import, and inheritance edges in two-pass mode (imports first, then calls/inheritance). |
