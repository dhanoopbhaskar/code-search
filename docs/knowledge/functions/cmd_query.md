---
type: Function
title: "cmd_query"
description: "Handler for the `query` subcommand: answers a question by bounded graph traversal."
resource: code_search/cli/main.py#cmd_query
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `query` subcommand: calls
[`GraphQueryService.query`](../types/GraphQueryService.md) to seed a bounded
traversal from the same reranked hits the search surface returns and prints
the result with [`render_query_text`](render_query_text.md) using
root-relative paths, or as JSON (with `freshness` and `query_time_ms`) under
`--json`. `--include-externals` keeps unresolved/external callee leaves that
are collapsed by default. Each call is written to the audit log as
`query_graph`. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_query(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `question`, `depth` (default 2), `max_nodes` (default 120), `edge_types` (default `CALLS,INHERITS`), `token_budget` (default 1500), `include_externals`, `json`, and the global `context_dir`/`verbose` are honoured. |

# Returns

`0` on success (including a `no_seed` outcome), `1` when the index is not initialised.
