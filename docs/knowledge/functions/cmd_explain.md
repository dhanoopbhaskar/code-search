---
type: Function
title: "cmd_explain"
description: "Handler for the `explain` subcommand: prints a symbol's metadata, relations, rationale, and linked docs."
resource: code_search/cli/main.py#cmd_explain
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `explain` subcommand: calls
[`GraphQueryService.explain`](../types/GraphQueryService.md) and prints the
result with [`render_explain_text`](render_explain_text.md) using
index-root-relative paths, or JSON under `--json`. Each call is audited as
`explain_symbol`. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_explain(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `symbol`, `depth` (default 1), `relations` (default `CALLS,INHERITS`), `json`, and the global options are honoured. |

# Returns

`0` when the outcome is `resolved`, `2` otherwise (unresolved or ambiguous
symbol), `1` when the index is not initialised.
