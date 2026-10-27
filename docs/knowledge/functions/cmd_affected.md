---
type: Function
title: "cmd_affected"
description: "Handler for the `affected` subcommand: reports symbols impacted by changed files."
resource: code_search/cli/main.py#cmd_affected
tags: [cli, function, graph]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:45:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handles the `affected` subcommand. Changed files come from explicit `paths` or
from git (`--since <ref>`, or `--base-branch <ref>`, which takes precedence) and
are resolved by [`GraphQueryService.detect_changes`](../types/GraphQueryService.md),
which shares its payload builder with the MCP `detect_changes` tool. The payload
carries the impacted symbols with risk labels, production/test separation, and
traversal provenance; text output is rendered by
[`render_changes_text`](render_changes_text.md), while `--json` emits the compact
payload (or the duplicated engine view with `--full`). Each call is audited as
`detect_changes`. Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_affected(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `paths`, `since`, `base_branch`, `scope` (`files`/`impact`/`tests`, default `impact`), `direction` (`inbound` default, `outbound`, `both`), `depth` (default 3, max 4), `fixpoint`, `edge_types` (default `CALLS,INHERITS`), `no_imports`, `seed_filter` (`all` default, or `product`), `json`, `full`, `pretty`, `meta`, and the global options are honoured. |

# Returns

`0` when the change request resolved, `1` when the index is not initialised or
no files changed, and `2` for an invalid scope, git ref, or argument.
