---
type: Function
title: "cmd_cypher"
description: "Run a read-only Cypher query over the indexed graph."
resource: code_search/cli/main.py#cmd_cypher
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Run a read-only Cypher query over the indexed graph.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_cypher(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `query`, `limit`, `offset`, `cursor`, `timeout_ms`, and `json` are honoured. |

# Returns

`0` when the query ran (including an empty result), `2` for an invalid, unsupported, timed-out, or failed query, or `1` when the index is not initialized.

# Notes

Shares the compiler, executor, and payload with the MCP `cypher_query`
tool. The query is read-only, bounded by `--limit`/`--timeout-ms`, and
paged with the generation-keyed cursor returned in the payload.
