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

Loads custom language configuration overrides from a JSON file. Returns
the parsed config as-is; merging it with the built-in language definitions
happens later in
[`LanguageConfig.merge_with_defaults`](../types/LanguageConfig.md).
Defined in [`engine.config`](../modules/engine/config.md).

# Signature

`def load_language_config(config_path: Path \| None = None) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `config_path` | `Path \| None` | Path to the JSON config file; defaults to `CODE_SEARCH_LANGUAGE_CONFIG`, then `language_config.json`. |

# Returns

The parsed JSON config (a `{"languages": [...]}` mapping), or an empty `{"languages": []}` when the file is missing or invalid.
