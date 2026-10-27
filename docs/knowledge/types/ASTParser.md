---
type: Class
title: "ASTParser"
description: "Tree-sitter based multi-language AST parser producing chunk boundaries and node trees."
resource: code_search/engine/parser.py#ASTParser
tags: [parsing, tree-sitter, ast]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/parser.py
    id: source-code
---

# Overview

Wraps tree-sitter grammars to parse source files into ASTs across
multiple languages, producing chunk boundaries consumed by the indexing
pipeline and parse trees consumed by
[`SymbolExtractor`](../types/SymbolExtractor.md). `.tsx` files are parsed
with the internal `tsx` grammar dialect while their public language token
stays `typescript`, so filters and stored values are unchanged. Declaration
nodes are normalised to canonical chunk types across grammars (Go
`type_spec`, Kotlin interfaces, Go `method_elem`), and YAML root `pair`
nodes are emitted as non-definition chunks. Defined in
[`engine.parser`](../modules/engine/parser.md).

# Methods

| Method | Description |
|---|---|
| `__init__(exclusion_patterns: set[str] \| None = None, language_config: LanguageConfig \| None = None, index_prose: bool = False, settings: Settings \| None = None, respect_gitignore: bool \| None = None) -> None` | Initialize the parser with optional exclusions and language overrides; *respect_gitignore* defaults to the settings value (or `True`). |
| `parse_file(file_path: Path, source_bytes: bytes \| None = None) -> Any` | Parse a single file into a tree-sitter tree, or `None` on failure. |
| `detect_language(file_path: Path, resource_extensions: tuple[str, ...] \| None = None) -> str \| None` | Return the language identifier for *file_path*, or `None` if unsupported. |
| `discover_files(root_path: Path, exclusion_patterns: set[str] \| None = None, include_resources: bool = False, resource_extensions: tuple[str, ...] \| None = None, index_prose: bool \| None = None) -> list[Path]` | Walk *root_path* and return all supported source files, skipping excluded dirs. |
| `get_node_text(node: object, source_bytes: bytes) -> str` | Return the source text covered by an AST node. |
| `get_node_range(node: object) -> tuple[int, int, int, int]` | Return `(row_start, col_start, row_end, col_end)` for an AST node. |
| `is_supported_file(file_path: Path) -> bool` | Return whether *file_path* has a supported source extension (also used to classify an unindexed path as unsupported rather than excluded). |
| `is_excluded_file(file_path: Path, root_path: Path) -> bool` | Check whether *file_path* is excluded by exclusion patterns or, when enabled, a `.gitignore` rule (see [`GitIgnoreMatcher`](GitIgnoreMatcher.md)). |
| `get_chunks_for_file(file_path: Path, source_bytes: bytes) -> list[ParsedNode]` | Extract indexable AST chunks (definitions, declarations, imports, comments, etc.), including JS/TS `function_declaration` and `lexical_declaration` anchors. |
| `_lexical_declaration_defines_function(node: object) -> bool` | Return whether a JS/TS `lexical_declaration` binds a function value (arrow function, function expression, or call such as `createAsyncThunk`). |
| `_canonical_chunk_node_type(node: object, node_type: str) -> str` | Map grammar-specific declaration nodes (Go `type_spec`/`method_elem`, Kotlin `object_declaration`/interfaces) onto canonical chunk types. |
