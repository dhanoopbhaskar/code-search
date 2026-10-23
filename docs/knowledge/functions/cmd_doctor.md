---
type: Function
title: "cmd_doctor"
description: "Handler for the `doctor` subcommand: reports index age, model availability, daemon state, and index size."
resource: code_search/cli/main.py#cmd_doctor
tags: [cli, function, diagnostics]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Prints a JSON diagnostic payload covering the context directory, index
status and age, graph database size, runtime profile and recorded layout,
daemon status, embedding-model availability, and whether the graph was
indexed (`--no-graph` builds report `graph_indexed: false`). Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_doctor(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed arguments carrying the global context/verbose options. |

# Returns

`0` on success.
