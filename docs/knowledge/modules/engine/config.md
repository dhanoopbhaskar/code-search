---
type: Module
title: "engine.config"
description: "Settings dataclass (env-var driven) with runtime-profile presets, platform-derived defaults, language configuration overlay, and path-based file classification helpers."
resource: code_search/engine/config.py
tags: [engine, config, settings]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/config.py
    id: source-code
---

# Overview

Provides application configuration and file-classification helpers.
Three responsibilities: (1) [`Settings`](../../types/Settings.md) — an
immutable, env-var-driven configuration dataclass covering indexing,
search, reranking, trust signals, freshness, graph traversal, metrics,
and the MCP server, with every field reading a `CODE_SEARCH_*`
environment variable. Two runtime presets (`standard`, `small`) select the
index layout (`legacy`/`compact`) and freshness mode
(`blocking`/`deferred`); explicit environment variables or CLI flags always
win over the preset. (2) [`LanguageConfig`](../../types/LanguageConfig.md) —
operator-supplied overrides of built-in language definitions
(extensions, grammar modules, chunk node types) loaded from JSON; (3)
path-classification helpers that determine whether a file is a test
file, non-canonical code (examples/legacy/generated/mocks), or a main
source file from path segments and filename conventions alone.

See [Config](../../config/index.md) for the full environment variable
reference.

# Key Classes

- [`LanguageConfig`](../../types/LanguageConfig.md) — merges user JSON overrides into built-in language definitions.
- [`Settings`](../../types/Settings.md) — the frozen dataclass carrying 176 tunable fields.

# Key Functions

- [`load_language_config`](../../functions/load_language_config.md) — load custom language configuration from JSON.

# Derived Defaults

Two knobs are derived rather than fixed, because the right value depends on the
host:

- `graph_cache_max_bytes` (`_graph_cache_bytes_default`) — an explicit
  `CODE_SEARCH_GRAPH_CACHE_MAX_BYTES` wins (`0` disables the cache); otherwise
  the budget is the smaller of 256 MB and a quarter of the memory the OS reports
  as available (`_available_memory_bytes`). A platform that cannot report memory
  gets the 256 MB ceiling instead of an unbounded cache.
- The SQLite tuning trio (`sqlite_cache_kib`, `sqlite_mmap_bytes`,
  `sqlite_temp_store_memory`) applies per connection and is deliberately
  modest so several connections stay inside the process budget.

`Settings.with_repo_expansions()` returns a copy pointing at a repository's own
`.code-search/expansions.json` pack when one exists, unless an explicit
`CODE_SEARCH_EXPANSION_FILE` (or constructor value) already chose a pack — the
operator keeps the final say.

# Internal Helpers

Path-classification predicates: `_is_test_root`, `_is_non_canonical_root`,
`_matches_test_filename`, `_matches_non_canonical_filename`,
`_is_test_file`, `_is_non_canonical`, `_is_dts_file`.
