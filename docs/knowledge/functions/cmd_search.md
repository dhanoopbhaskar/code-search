---
type: Function
title: "cmd_search"
description: "Handler for the `search` subcommand: runs a hybrid search query and prints results."
resource: src/cli/main.py#cmd_search
tags: [cli, function, search]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `search` subcommand, invoking
[`HybridSearch.search`](/types/HybridSearch.md) and formatting the
response envelope for terminal output. Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_search(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments including query text, limit, language, and content filters. |

# Returns

Process exit code.
