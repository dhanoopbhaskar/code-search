---
type: Function
title: "clear_state"
description: "Remove the daemon lifecycle-state file, ignoring a missing file."
resource: code_search/engine/daemon.py#clear_state
tags: [daemon, function, lifecycle]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Deletes `code-search.state` from the context directory during daemon
shutdown. A missing file is not an error. Defined in
[`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def clear_state(context_dir: Path) -> None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `context_dir` | `Path` | The daemon's context directory. |

# Returns

None.
