---
type: Function
title: "cmd_metrics"
description: "Handler for the `metrics` subcommand: prints latency percentiles and redaction counts."
resource: src/cli/main.py#cmd_metrics
tags: [cli, function, observability]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `metrics` subcommand, invoking
[`MetricsCollector.percentiles`](/types/MetricsCollector.md) to print
health statistics. Defined in [`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_metrics(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the `metrics` subcommand. |

# Returns

Process exit code.
