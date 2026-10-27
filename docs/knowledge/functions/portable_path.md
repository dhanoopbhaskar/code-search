---
type: Function
title: "portable_path"
description: "Return path in POSIX spelling."
resource: code_search/engine/paths.py#portable_path
tags: [engine, function, paths]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/paths.py
    id: source-code
---

# Overview

Return `path` in POSIX spelling.

Defined in [`engine.paths`](../modules/engine/paths.md).

# Signature

`def portable_path(path: str | Path) -> str`

# Parameters

| Name | Description |
|---|---|
| `path` | A path, absolute or relative, as a string or `Path`. |

# Returns

The path with `/` separators. On POSIX this is the input unchanged.

# Notes

Stored paths are ranked against, compared as substrings, embedded in FQNs,
and matched by callers that assume `/` separators. Rendering through
`as_posix` keeps one spelling on every platform instead
of letting the host separator leak into the index.
