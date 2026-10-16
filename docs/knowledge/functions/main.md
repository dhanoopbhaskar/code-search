---
type: Function
title: "main"
description: "Parse arguments and dispatch to the selected subcommand handler."
resource: code_search/cli/main.py#main
tags: [cli, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

CLI entry point: parses `sys.argv` via
[`build_parser`](build_parser.md) and dispatches to the
matching `cmd_*` handler. Defined in
[`cli.main`](../modules/cli/main.md).

# Signature

`def main() -> None`

# Returns

`None`. The process exits with the chosen handler's exit code, or `1` on an
unexpected exception.
