---
type: Function
title: "cmd_search"
description: "Handler for the `search` subcommand: runs a hybrid search query and prints results."
resource: code_search/cli/main.py#cmd_search
tags: [cli, function, search]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `search` subcommand, invoking
[`HybridSearch.search`](../types/HybridSearch.md) and formatting the
response envelope for terminal output. Results are printed with root-relative
paths; `--explain-ranking` additionally prints the per-result score breakdown
and the ranking explanation instead of forwarding to the daemon. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_search(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `query`, `limit`, `language`, `content`, `include_tests` (off by default; `--include-tests` opts in), `matching`, `json`, `no_model`, `regex`, `compact`, `max_snippet_lines`, `explain_ranking`, and `no_startup_check` are honoured. |

# Returns

A process exit code: `0` on success, `1` when the index is not initialised.
