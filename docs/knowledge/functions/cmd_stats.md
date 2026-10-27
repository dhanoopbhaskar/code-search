---
type: Function
title: "cmd_stats"
description: "Handler for the `stats` subcommand: prints the runtime profile, index layout, and disk footprint."
resource: code_search/cli/main.py#cmd_stats
tags: [cli, function, observability]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Reports the effective runtime profile and why it was chosen
(`profile_reason`), the recorded index layout, freshness mode, index age,
graph/vector file sizes (including the append-only `.files` dictionary),
total footprint, and row counts for the main content tables. Text or JSON
output is selected with `--format`. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_stats(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `format` selects `text` or `json`. |

# Returns

`0` on success.
