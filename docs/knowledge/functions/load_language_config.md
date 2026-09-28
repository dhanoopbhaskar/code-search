---
type: Function
title: "load_language_config"
description: "Load custom language configuration from JSON."
resource: src/engine/config.py#load_language_config
tags: [config, language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

Loads custom language configuration overrides from a JSON file, merging
them with the built-in [`LanguageConfig`](/types/LanguageConfig.md)
table. Defined in [`engine.config`](/modules/engine/config.md).

# Signature

`def load_language_config(path: Path) -> dict[str, LanguageConfig]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `path` | `Path` | Path to the JSON language-configuration file. |

# Returns

Mapping of language name to its [`LanguageConfig`](/types/LanguageConfig.md).
