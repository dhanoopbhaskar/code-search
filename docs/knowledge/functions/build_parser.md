---
type: Function
title: "build_parser"
description: "Build the full argparse tree with all subcommands."
resource: src/cli/main.py#build_parser
tags: [cli, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Builds the full `argparse.ArgumentParser` tree, registering every
subcommand (index, search, symbol, graph, implementations, metrics,
serve, list-languages, download-models, daemon). Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def build_parser() -> argparse.ArgumentParser`

# Returns

The configured top-level parser with all subcommands attached.
