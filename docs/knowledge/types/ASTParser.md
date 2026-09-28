---
type: Class
title: "ASTParser"
description: "Tree-sitter based multi-language AST parser producing chunk boundaries and node trees."
resource: src/engine/parser.py#ASTParser
tags: [parsing, tree-sitter, ast]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/parser.py
    id: source-code
---

# Overview

Wraps tree-sitter grammars to parse source files into ASTs across
multiple languages, producing chunk boundaries used by
[`SymbolExtractor`](/types/SymbolExtractor.md) and the indexing pipeline.
Defined in [`engine.parser`](/modules/engine/parser.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, settings: Settings \| None = None) -> None` | Initialize the parser, lazily loading tree-sitter grammars per language. |
| `parse(self, file_path: Path, source_bytes: bytes) -> Any` | Parse *source_bytes* for the language inferred from *file_path*; returns a tree-sitter tree. |
| `get_chunks(self, file_path: Path, source_bytes: bytes) -> list[dict[str, Any]]` | Return chunk boundaries (declarations, bodies, line ranges) for a parsed file. |
| `supported_language(self, file_path: Path) -> str \| None` | Return the inferred language name for *file_path*, or `None` if unsupported. |
