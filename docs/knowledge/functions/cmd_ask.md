---
type: Function
title: "cmd_ask"
description: "Answer one question by routing it to the right retrieval surface."
resource: code_search/cli/main.py#cmd_ask
tags: [cli, function, main]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/cli/main.py
    id: source-code
---

# Overview

Answer one question by routing it to the right retrieval surface.

Defined in [`cli.main`](../modules/cli/main.md).

# Signature

`def cmd_ask(args: argparse.Namespace) -> int`

# Parameters

| Name | Description |
|---|---|
| `args` | Parsed arguments; `question`, `limit`, `budget`, `strict`, `include_tests`, `content`, `json`, and `pretty` are honoured. |

# Returns

`0` on a resolved answer, `2` when the index is unavailable.

# Notes

The router is `ask`; this command adds the
shared freshness signal, an audit entry, and text/JSON rendering.
