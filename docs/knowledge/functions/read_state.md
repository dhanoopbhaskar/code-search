---
type: Function
title: "read_state"
description: "Return the recorded daemon lifecycle state, or None when absent."
resource: code_search/engine/daemon.py#read_state
tags: [daemon, function, lifecycle]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Reads the daemon lifecycle state from `code-search.state` in the context
directory. Missing or unreadable files yield `None`. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def read_state(context_dir: Path) -> str | None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory. |

# Returns

The recorded state string, or `None` when no state file exists.
