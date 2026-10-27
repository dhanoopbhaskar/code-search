---
type: Module
title: "cli.main"
description: "CLI entry point: subcommands for indexing, searching, asking, graph discovery and traversal, symbol reading, diagnostics, metrics, serving, and the daemon."
resource: code_search/cli/main.py
tags: [cli, entry-point]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
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
| `ask` | Route one question to the right surface and print one compact answer |
| `symbol` | Look up a symbol definition by fully qualified name (FQN) |
| `view` | Read a symbol or file under a compact outline/body contract with `--max-lines` and `--budget` |
| `graph` | Traverse the call graph for a symbol (callers/callees/implements) |
| `schema` | Describe the graph labels, edge types, tiers, and coverage an agent can query |
| `outline` | List one file's declarations in source order |
| `symbols` | Search symbols by structure: regex name/QN, kind, file, and degree |
| `dead-code` | Report callables with no proven production reference |
| `coverage` | Report index gaps for requested paths/scopes |
| `cypher` | Run a read-only Cypher query over the indexed graph |
| `implementations` | Find static implementations of an interface member or type |
| `find-related` | Find chunks semantically related to a file/line anchor (mirrors the MCP tool) |
| `query` | Answer a natural-language or identifier question by bounded graph traversal |
| `path` | Shortest graph path between two symbols |
| `explain` | A symbol's metadata, relations, rationale comments, and linked docs |
| `affected` | Symbols impacted by changed files (explicit paths or `--since <git-ref>`) |
| `map` | Deterministic architecture report (god nodes, communities, import cycles) |
| `metrics` | Print index health and usage metrics (human, JSON, or Prometheus) |
| `stats` | Print the runtime profile, index layout, freshness mode, and disk footprint |
| `doctor` | Report index age, model availability, daemon state, and index size as JSON |
| `start` / `status` | Aliases for `daemon start` / `daemon status` |
| `serve` | Start the MCP server over stdio |
| `list-languages` | List supported languages with extensions and grammar mappings |
| `download-models` | Download embedding models to the Hugging Face cache |
| `daemon` | Manage the local query daemon (AF_UNIX socket or named pipe): `start`, `stop`, `status`, `wait`, and foreground `run` |

# Key Functions

- [`build_parser`](../../functions/build_parser.md) — build the full argparse tree with all subcommands.
- [`main`](../../functions/main.md) — parse arguments and dispatch to the selected subcommand handler.
- [`cmd_index`](../../functions/cmd_index.md), [`cmd_search`](../../functions/cmd_search.md), [`cmd_ask`](../../functions/cmd_ask.md), [`cmd_symbol`](../../functions/cmd_symbol.md), [`cmd_view`](../../functions/cmd_view.md), [`cmd_graph`](../../functions/cmd_graph.md), [`cmd_schema`](../../functions/cmd_schema.md), [`cmd_outline`](../../functions/cmd_outline.md), [`cmd_symbols`](../../functions/cmd_symbols.md), [`cmd_dead_code`](../../functions/cmd_dead_code.md), [`cmd_coverage`](../../functions/cmd_coverage.md), [`cmd_cypher`](../../functions/cmd_cypher.md), [`cmd_implementations`](../../functions/cmd_implementations.md), [`cmd_find_related`](../../functions/cmd_find_related.md), [`cmd_query`](../../functions/cmd_query.md), [`cmd_path`](../../functions/cmd_path.md), [`cmd_explain`](../../functions/cmd_explain.md), [`cmd_affected`](../../functions/cmd_affected.md), [`cmd_map`](../../functions/cmd_map.md), [`cmd_metrics`](../../functions/cmd_metrics.md), [`cmd_stats`](../../functions/cmd_stats.md), [`cmd_doctor`](../../functions/cmd_doctor.md), [`cmd_start`](../../functions/cmd_start.md), [`cmd_status`](../../functions/cmd_status.md), [`cmd_serve`](../../functions/cmd_serve.md), [`cmd_list_languages`](../../functions/cmd_list_languages.md), [`cmd_daemon`](../../functions/cmd_daemon.md), [`cmd_daemon_run`](../../functions/cmd_daemon_run.md), [`cmd_download_models`](../../functions/cmd_download_models.md) — one handler per subcommand.

# Discovery Commands

`schema`, `outline`, `symbols`, `dead-code`, and `coverage` are thin CLI
wrappers over [`engine.graph_surface`](../engine/graph_surface.md), and `cypher`
wraps [`engine.cypher`](../engine/cypher.md); `ask` wraps
[`engine.ask`](../engine/ask.md). Each shares its payload builder with the
matching MCP tool, so the CLI and the agent see identical shapes. They follow the
same exit-code contract: `0` when the command produced an answer (including an
empty result), `2` when nothing matched, a filter was invalid, or the graph was
not indexed, `3` for an ambiguous symbol reference, and `1` when the index is not
initialized.

`cypher` bounds its query with `--limit` and `--timeout-ms` and pages with the
generation-keyed `--cursor` echoed in the payload. `dead-code` reports
candidates with their caveats and never recommends deleting code.

# Output and Startup Options

`search` accepts `--regex` (exhaustive mode only), `--explain-ranking`
(per-result score components), `--compact`/`--no-compact` (agent-sized JSON
is the default), `--pretty`, `--max-snippet-lines`, `--paths-only`
(location and classification fields only), and `--allow-weak` (bypass the
post-rank abstention gate). JSON output is compact by default and reports
paths/FQNs relative to the index root.

`index` accepts `--runtime-profile` (`standard`/`small`),
`--index-layout` (`legacy`/`compact`), and `--no-graph`; the query commands
accept `--runtime-profile` and `--freshness-mode`
(`blocking`/`deferred`). The flags replace the profile-derived defaults for
that invocation. The global
`--no-startup-check` skips transparent daemon auto-start for a single
invocation. `symbol`, `graph`, `implementations`, and `find-related`
forward to the resident daemon by default. `daemon wait --timeout <seconds>`
(default 30) blocks until the daemon is both running and warm, printing
`ready`, so a script can gate on readiness instead of polling
`daemon status`. `graph` reports edge-resolution
coverage and accepts `--explain-unresolved`; a `--no-graph` index is
reported as `graph_not_indexed`.

# Internal Helpers

Private (underscore-prefixed) helpers handle component wiring
(`_initialize_components`, with `settings`, `load_vectors`, and
`for_index` parameters so symbol-only commands skip the vector sidecar),
profile/flag resolution (`_settings_for_args`), graph availability
reporting (`_graph_not_indexed_message`), byte/age formatting
(`_human_bytes`, `_index_age_seconds`), graph-service construction
(`_graph_query_service`), edge-type parsing (`_parse_edge_types`), the git
diff used by `affected` (`_git_changed_files`), daemon forwarding (`_try_forward_to_daemon`,
`_ensure_resident_service`), and human-readable output formatting
(`_print_search_results`, `_print_match_breakdown`,
`_print_ranking_explanation`, `_compact_signature`,
`_print_symbol_details`, `_print_ambiguous_candidates`,
`_print_graph_results`, `_print_implementations`,
`_print_human_metrics`, `_print_prometheus_metrics`).
