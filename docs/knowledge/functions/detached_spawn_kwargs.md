---
type: Function
title: "detached_spawn_kwargs"
description: "Return `Popen` options that detach the daemon from the invoking CLI."
resource: code_search/engine/daemon.py#detached_spawn_kwargs
tags: [engine, function, daemon]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/daemon.py
    id: source-code
---

# Overview

Return `Popen` options that detach the daemon from the invoking CLI.

Defined in [`engine.daemon`](../modules/engine/daemon.md).

# Signature

`def detached_spawn_kwargs() -> dict[str, Any]`

# Returns

Keyword arguments to pass to `Popen`.

# Notes

On POSIX a new session lets the daemon outlive the shell. On Windows
`start_new_session` is accepted but ignored, so `DETACHED_PROCESS` is
required to give the child no console of its own; `CREATE_NEW_PROCESS_GROUP`
keeps a Ctrl+C in the parent's console from reaching it.
