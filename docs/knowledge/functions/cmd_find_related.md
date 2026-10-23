---
type: Function
title: "cmd_find_related"
description: "Handler for the find-related subcommand: prints chunks semantically related to a file/line anchor."
resource: code_search/cli/main.py#cmd_find_related
tags: [cli, command, related]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Handler for the `find-related` subcommand: returns chunks semantically
related to the chunk at a file/line anchor. It first tries the resident
daemon, then falls back to in-process ranking via the shared
[`find_related`](find_related.md) function, so the CLI, daemon, and MCP
surfaces report the same neighbours and status. Text output renders paths
relative to the indexed root; JSON output keeps the same portable spelling.
Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_find_related(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments; `file_path`, `line`, `limit`, and `json` are honoured. |

# Returns

A process exit code: `0` on success, `1` when the index is not initialised.
