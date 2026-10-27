---
type: Module
title: "engine.graph_surface"
description: "Read-only, agent-facing discovery surfaces: graph schema, file outline, structural symbol search, dead code, and index coverage, all returning shared CLI/MCP payloads."
resource: code_search/engine/graph_surface.py
tags: [engine, graph, discovery, agent-surface]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_surface.py
    id: source-code
---

# Overview

[`engine.graph_query`](graph_query.md) answers neighbourhood and path questions.
This module answers the *discovery* questions an agent must ask first: what
labels and edge types exist, what a file declares, which symbols match
structural filters, and where the index has gaps.

Every function is read-only, deterministic, and bounded, and returns a plain
dictionary so the CLI and the MCP server share one payload shape. Transport
concerns — freshness signals and audit entries — stay in the calling surface.

# Surfaces

| Function | Question it answers | Bound |
|---|---|---|
| [`get_graph_schema`](../../functions/get_graph_schema.md) | Which labels, edge types, tiers, and coverage counts can I query? | 500 node labels, 1,000 sampled edge-property rows |
| [`get_file_outline`](../../functions/get_file_outline.md) | What does one file declare, in source order? | 500 declarations |
| [`search_symbols`](../../functions/search_symbols.md) | Which symbols match regex/kind/file/degree filters? | 200 symbols, 10 neighbours per symbol |
| [`find_dead_code`](../../functions/find_dead_code.md) | Which callables have no proven production reference? | 200 candidates |
| [`check_index_coverage`](../../functions/check_index_coverage.md) | What gap was recorded for these paths or scopes? | 1,000 rows |
| [`changed_files_since`](../../functions/changed_files_since.md) | Which working-tree files differ from a git ref? | — |

Each has a matching `render_*_text` helper for the CLI path.

# Evidence Discipline

The payloads carry their own limits rather than leaving them implicit:

- `check_index_coverage` distinguishes `no_recorded_issue` ("indexed, no gap
  recorded") from `not_indexed`/`skipped`/`excluded`. A clean result is not
  proof of completeness.
- `find_dead_code` reports unresolved same-name references and test-only usage
  per row, because those are exactly the cases where a dynamic or external
  caller could still keep the symbol alive. It is evidence, never a deletion
  recommendation.
- `get_file_outline` returns `outcome: not_indexed` when no declaration for the
  file exists, so "empty file" and "absent from the index" stay distinguishable.
- `search_symbols` returns `outcome: invalid_argument` for a bad regex instead
  of raising.

# Internal Helpers

Path resolution goes through `_stored_symbol_path`/`_stored_checksum_path` (the
spelling the indexer actually wrote, including Windows spellings) and
`_relative_or_absolute`. `_degree_table_sql` aggregates resolved degrees in one
CTE; `_connected_neighbors` fetches up to ten neighbours per symbol in a single
batched query. `_file_freshness` compares the recorded checksum row with the
file on disk, and `_classify_unindexed_path` uses the parser to tell "excluded
on purpose" from "unsupported language".
