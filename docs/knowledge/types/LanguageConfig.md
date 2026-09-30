---
type: Class
title: "LanguageConfig"
description: "Operator-supplied overrides of the built-in language definitions (extensions, grammar modules, chunk node types)."
resource: src/engine/config.py#LanguageConfig
tags: [config, language, class]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

Operator-supplied overrides of the built-in language definitions (extensions, grammar modules, and chunk node types). Loads a JSON file and merges it over the defaults so custom extensions or AST chunk node types can be injected without editing source. Defined in
[`engine.config`](../modules/engine/config.md).

# Methods

| Method | Description |
|---|---|
| `__init__(config_path: Path \| None = None) -> None` | Create a language config loaded from *config_path*. |
| `merge_with_defaults(default_languages: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]` | Merge built-in language definitions with user-provided overrides. |
| `get_supported_languages() -> set[str]` | Return the names of all languages after merging with defaults. |
| `get_language_config(name: str) -> dict[str, Any] \| None` | Return the merged configuration dict for *name*. |
| `get_extensions_map() -> dict[str, str]` | Return a mapping of file extension (leading dot) to language name. |
