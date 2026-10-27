---
type: Module
title: "engine.parser"
description: "Tree-sitter based AST parsing and file discovery for the multi-language indexing pipeline, with canonical chunk types across grammars."
resource: code_search/engine/parser.py
tags: [engine, parser, ast, tree-sitter]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/parser.py
    id: source-code
---

# Overview

AST-based code parser that uses tree-sitter grammars to parse source
files into Abstract Syntax Trees (ASTs) and extract meaningful chunks
(function/class/interface definitions, variable declarations, imports,
comments, etc.) for indexing in a multi-language code search engine.
Supports language detection via file extensions, file discovery with
configurable exclusion patterns, and extensible language definitions
through [`LanguageConfig`](../../types/LanguageConfig.md). `.tsx` files are
parsed with the internal `tsx` grammar dialect while the stored language
token remains `typescript`.

Language-specific declaration nodes are normalised to canonical chunk
types: Go `type_spec` becomes `class_declaration` (struct),
`interface_declaration` (interface), or `type_alias`; Kotlin
`object_declaration` becomes a class and `interface` class declarations
become interfaces; Go `method_elem` becomes `method_declaration`. YAML root
`pair` nodes are emitted as non-definition `pair` chunks, and YAML
`document` nodes are treated as chunk parents like Python modules.

# Key Constants

| Constant | Purpose |
|---|---|
| `LANGUAGE_MAP` | Maps file extensions to internal language identifiers |
| `EXCLUSION_PATTERNS` | Directory names skipped during file discovery (`.git`, `node_modules`, ...) |
| `PROSE_EXTENSIONS` | Extensions for prose/transient files not indexed by default |
| `LOCKFILE_NAMES` | Well-known package lockfile names |
| `SUPPORTED_LANGUAGES` | 15 languages with bundled tree-sitter grammars |
| `LANGUAGE_GRAMMAR_MAP` | Maps language names (including the internal `tsx` dialect) to tree-sitter grammar Python packages |
| `EXTENSIONLESS_INFRA_FILES` | Extension-less infra filenames (`dockerfile`, `makefile`) mapped to language tokens |
| `EXCLUDED_FILE_NAMES` | File names never indexed regardless of language (`.DS_Store`) |

# Key Classes

- [`ASTParser`](../../types/ASTParser.md) — parses source files using tree-sitter and extracts indexable AST chunks.
- [`GitIgnoreMatcher`](../../types/GitIgnoreMatcher.md) — evaluates repository `.gitignore` files during discovery and stale pruning.

# Internal Helpers

`_init_grammar`/`_get_language` lazily import and cache tree-sitter
`Language` objects on first use; `_is_lockfile` recognizes well-known
lockfile names. (`_init_grammars` is an unused eager-initialisation
helper.) `_canonical_chunk_node_type` performs the grammar-specific
declaration remapping described above.
