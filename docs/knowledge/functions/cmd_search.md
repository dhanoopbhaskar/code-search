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
response envelope for terminal output. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_search(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `query`, `limit`, `language`, `include_tests`, `json`, `no_model` are honoured. |

# Returns

A process exit code: `0` on success, `1` when the index is not initialised.
