---
type: Module
title: "cli.main"
description: "CLI entry point: subcommands for indexing, searching, graph traversal, symbol lookup, metrics, serving, and the daemon."
resource: src/cli/main.py
tags: [cli, entry-point]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

The CLI entry point for the code-search context engine. Provides
subcommands for indexing codebases, searching code semantically,
navigating call graphs, looking up symbol definitions, viewing metrics,
starting the MCP server, and managing a local daemon for faster repeated
queries.

# Subcommands

| Subcommand | Purpose |
|---|---|
| `index` | Build or update the code index; supports incremental updates, watching, exclusions |
| `search` | Natural-language search over the index, semantic + lexical ranking |
| `symbol` | Look up a symbol definition by fully qualified name (FQN) |
| `graph` | Traverse the call graph for a symbol (callers/callees/implements) |
| `implementations` | Find static implementations of an interface member or type |
| `metrics` | Print index health and usage metrics (human, JSON, or Prometheus) |
| `serve` | Start the MCP server over stdio |
| `list-languages` | List supported languages with extensions and grammar mappings |
| `download-models` | Download embedding models to the Hugging Face cache |
| `daemon` | Manage the local unix-socket query daemon (start/stop/status/run) |

# Key Functions

- [`build_parser`](/functions/build_parser.md) — build the full argparse tree with all subcommands.
- [`main`](/functions/main.md) — parse arguments and dispatch to the selected subcommand handler.
- [`cmd_index`](/functions/cmd_index.md), [`cmd_search`](/functions/cmd_search.md), [`cmd_symbol`](/functions/cmd_symbol.md), [`cmd_graph`](/functions/cmd_graph.md), [`cmd_implementations`](/functions/cmd_implementations.md), [`cmd_metrics`](/functions/cmd_metrics.md), [`cmd_serve`](/functions/cmd_serve.md), [`cmd_list_languages`](/functions/cmd_list_languages.md), [`cmd_daemon`](/functions/cmd_daemon.md), [`cmd_daemon_run`](/functions/cmd_daemon_run.md), [`cmd_download_models`](/functions/cmd_download_models.md) — one handler per subcommand.

# Internal Helpers

Private (underscore-prefixed) helpers handle component wiring
(`_initialize_components`), daemon forwarding (`_try_forward_to_daemon`,
`_ensure_resident_service`), and human-readable output formatting
(`_print_search_results`, `_print_symbol_details`,
`_print_graph_results`, `_print_implementations`,
`_print_human_metrics`, `_print_prometheus_metrics`).
