---
type: Function
title: "cmd_search"
description: "Handler for the `search` subcommand: runs a hybrid search query and prints results."
resource: code_search/cli/main.py#cmd_search
tags: [cli, function, search]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
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
and the ranking explanation instead of forwarding to the daemon. Normal
queries forward to the resident daemon when one is available.

`--allow-weak` bypasses the post-rank abstention gate, `--paths-only` returns
only location and classification fields, and `--pretty`/`--no-compact` select
indented JSON. The default compact snippet budget is 10 lines, and
`--max-snippet-lines 0` returns no content. `--runtime-profile`,
`--index-layout`, and `--freshness-mode` replace the profile-derived defaults
for the invocation. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_search(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `query`, `limit`, `language`, `content`, `include_tests` (off by default; `--include-tests` opts in), `matching`, `json`, `no_model`, `regex`, `compact`, `pretty`, `paths_only`, `allow_weak`, `max_snippet_lines`, `explain_ranking`, `runtime_profile`, `index_layout`, `freshness_mode`, and `no_startup_check` are honoured. |

# Returns

A process exit code: `0` on success, `1` when the index is not initialised.
