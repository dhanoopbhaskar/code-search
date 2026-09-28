---
type: Module
title: "engine.parser"
description: "Tree-sitter based AST parsing and file discovery for the multi-language indexing pipeline."
resource: src/engine/parser.py
tags: [engine, parser, ast, tree-sitter]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/parser.py
    id: source-code
---

# Overview

AST-based code parser that uses tree-sitter grammars to parse source
files into Abstract Syntax Trees (ASTs) and extract meaningful chunks
(function/class/interface definitions, variable declarations, imports,
comments, etc.) for indexing in a multi-language code search engine.
Supports language detection via file extensions, file discovery with
configurable exclusion patterns, and extensible language definitions
through [`LanguageConfig`](/types/LanguageConfig.md).

# Key Constants

| Constant | Purpose |
|---|---|
| `LANGUAGE_MAP` | Maps file extensions to internal language identifiers |
| `EXCLUSION_PATTERNS` | Directory names skipped during file discovery (`.git`, `node_modules`, ...) |
| `PROSE_EXTENSIONS` | Extensions for prose/transient files not indexed by default |
| `LOCKFILE_NAMES` | Well-known package lockfile names |
| `SUPPORTED_LANGUAGES` | 14 languages with bundled tree-sitter grammars |
| `LANGUAGE_GRAMMAR_MAP` | Maps language names to tree-sitter grammar Python packages |
| `EXTENSIONLESS_INFRA_FILES` | Extension-less infra filenames (`dockerfile`, `makefile`) mapped to language tokens |

# Key Classes

- [`ASTParser`](/types/ASTParser.md) — parses source files using tree-sitter and extracts indexable AST chunks.

# Internal Helpers

`_init_grammar`/`_init_grammars`/`_get_language` lazily import and cache
tree-sitter `Language` objects; `_is_lockfile` recognizes well-known
lockfile names.
