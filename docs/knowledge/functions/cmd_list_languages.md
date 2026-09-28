---
type: Function
title: "cmd_list_languages"
description: "Handler for the `list-languages` subcommand: prints supported languages."
resource: src/cli/main.py#cmd_list_languages
tags: [cli, function, language]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `list-languages` subcommand, printing all
[`LanguageConfig`](/types/LanguageConfig.md) entries the parser supports.
Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_list_languages(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the `list-languages` subcommand. |

# Returns

Process exit code.
