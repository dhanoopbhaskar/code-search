---
type: Class
title: "LanguageConfig"
description: "Per-language configuration (extensions, tree-sitter grammar, comment syntax)."
resource: src/engine/config.py#LanguageConfig
tags: [config, language, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

Dataclass describing per-language configuration: file extensions,
tree-sitter grammar name, and comment syntax. Defined in
[`engine.config`](/modules/engine/config.md).

# Schema

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Language identifier (e.g. `"python"`). |
| `extensions` | `list[str]` | File extensions mapped to this language. |
| `grammar` | `str` | Tree-sitter grammar module name. |
| `line_comment` | `str \| None` | Line-comment prefix, if any. |
| `block_comment` | `tuple[str, str] \| None` | Block-comment start/end markers, if any. |
