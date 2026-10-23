---
type: Module
title: "cli.main"
description: "CLI entry point: subcommands for indexing, searching, graph traversal, symbol lookup, metrics, serving, and the daemon."
resource: code_search/cli/main.py
tags: [cli, entry-point]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
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
| `find-related` | Find chunks semantically related to a file/line anchor (mirrors the MCP tool) |
| `query` | Answer a natural-language or identifier question by bounded graph traversal |
| `path` | Shortest graph path between two symbols |
| `explain` | A symbol's metadata, relations, rationale comments, and linked docs |
| `affected` | Symbols impacted by changed files (explicit paths or `--since <git-ref>`) |
| `map` | Deterministic architecture report (god nodes, communities, import cycles) |
| `metrics` | Print index health and usage metrics (human, JSON, or Prometheus) |
| `serve` | Start the MCP server over stdio |
| `list-languages` | List supported languages with extensions and grammar mappings |
| `download-models` | Download embedding models to the Hugging Face cache |
| `daemon` | Manage the local AF_UNIX socket query daemon (start/stop/status/run) |

# Key Functions

- [`build_parser`](../../functions/build_parser.md) — build the full argparse tree with all subcommands.
- [`main`](../../functions/main.md) — parse arguments and dispatch to the selected subcommand handler.
- [`cmd_index`](../../functions/cmd_index.md), [`cmd_search`](../../functions/cmd_search.md), [`cmd_symbol`](../../functions/cmd_symbol.md), [`cmd_graph`](../../functions/cmd_graph.md), [`cmd_implementations`](../../functions/cmd_implementations.md), [`cmd_find_related`](../../functions/cmd_find_related.md), [`cmd_query`](../../functions/cmd_query.md), [`cmd_path`](../../functions/cmd_path.md), [`cmd_explain`](../../functions/cmd_explain.md), [`cmd_affected`](../../functions/cmd_affected.md), [`cmd_map`](../../functions/cmd_map.md), [`cmd_metrics`](../../functions/cmd_metrics.md), [`cmd_serve`](../../functions/cmd_serve.md), [`cmd_list_languages`](../../functions/cmd_list_languages.md), [`cmd_daemon`](../../functions/cmd_daemon.md), [`cmd_daemon_run`](../../functions/cmd_daemon_run.md), [`cmd_download_models`](../../functions/cmd_download_models.md) — one handler per subcommand.

# Output and Startup Options

`search` accepts `--regex` (exhaustive mode only), `--explain-ranking`
(per-result score components), `--compact`/`--no-compact` (agent-sized JSON
is the default), and `--max-snippet-lines`. JSON output is compact by
default and reports paths/FQNs relative to the index root. The global
`--no-startup-check` skips transparent daemon auto-start for a single
invocation.

# Internal Helpers

Private (underscore-prefixed) helpers handle component wiring
(`_initialize_components`), graph-service construction
(`_graph_query_service`), edge-type parsing (`_parse_edge_types`), the git
diff used by `affected` (`_git_changed_files`), daemon forwarding (`_try_forward_to_daemon`,
`_ensure_resident_service`), and human-readable output formatting
(`_print_search_results`, `_print_match_breakdown`,
`_print_ranking_explanation`, `_compact_signature`,
`_print_symbol_details`, `_print_ambiguous_candidates`,
`_print_graph_results`, `_print_implementations`,
`_print_human_metrics`, `_print_prometheus_metrics`).
