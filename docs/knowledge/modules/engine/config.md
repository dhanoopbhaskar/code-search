---
type: Module
title: "engine.config"
description: "Settings dataclass (env-var driven), language configuration overlay, and path-based file classification helpers."
resource: src/engine/config.py
tags: [engine, config, settings]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

Provides application configuration and file-classification helpers.
Three responsibilities: (1) [`Settings`](/types/Settings.md) — an
immutable, env-var-driven configuration dataclass covering indexing,
search, reranking, trust signals, freshness, graph traversal, metrics,
and the MCP server, with every field reading a `CODE_SEARCH_*`
environment variable; (2) [`LanguageConfig`](/types/LanguageConfig.md) —
operator-supplied overrides of built-in language definitions
(extensions, grammar modules, chunk node types) loaded from JSON; (3)
path-classification helpers that determine whether a file is a test
file, non-canonical code (examples/legacy/generated/mocks), or a main
source file from path segments and filename conventions alone.

See [Config](/config/index.md) for the full environment variable
reference.

# Key Classes

- [`LanguageConfig`](/types/LanguageConfig.md) — merges user JSON overrides into built-in language definitions.
- [`Settings`](/types/Settings.md) — the frozen dataclass carrying 150+ tunable fields.

# Key Functions

- [`load_language_config`](/functions/load_language_config.md) — load custom language configuration from JSON.

# Internal Helpers

Path-classification predicates: `_is_test_root`, `_is_non_canonical_root`,
`_matches_test_filename`, `_matches_non_canonical_filename`,
`_is_test_file`, `_is_non_canonical`, `_is_dts_file`.
