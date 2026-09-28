---
type: Function
title: "cmd_download_models"
description: "Handler for the `download-models` subcommand: fetches the embedding model into the local models directory."
resource: src/cli/main.py#cmd_download_models
tags: [cli, function, embeddings]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/main.py
    id: source-code
---

# Overview

Handles the `download-models` subcommand, fetching the Model2Vec
embedding model (`potion-code-16m-32d`) into the local `models/`
directory, temporarily lifting air-gap enforcement via
[`allow_downloads`](/functions/allow_downloads.md). Defined in
[`cli.main`](/modules/cli/main.md).

# Signature

`def cmd_download_models(args: argparse.Namespace) -> int`

# Parameters

| Name | Type | Description |
|---|---|---|
| `args` | `argparse.Namespace` | Parsed CLI arguments for the `download-models` subcommand. |

# Returns

Process exit code.
