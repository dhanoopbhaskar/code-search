---
type: Function
title: "cmd_affected"
description: "Handler for the `affected` subcommand: reports symbols impacted by changed files."
resource: code_search/cli/main.py#cmd_affected
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `affected` subcommand. Changed files come from explicit `paths`
and, with `--since <ref>`, from `git diff --name-only <ref>` run in the index
root. The files are passed to
[`GraphQueryService.impact`](../types/GraphQueryService.md); the text output
groups impacted symbols by file and tags test files. Each call is audited as
`get_impact`. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_affected(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `paths`, `since`, `depth` (default 3), `json`, and the global options are honoured. |

# Returns

`0` on success; `1` when the index is not initialised, git fails to resolve
`--since`, or no changed files were supplied.
