---
type: Function
title: "repo_relative_path"
description: "Return path relative to root, or unchanged when it lies outside it."
resource: code_search/engine/paths.py#repo_relative_path
tags: [engine, function, paths]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/paths.py
    id: source-code
---

# Overview

Return `path` relative to `root`, or unchanged when it lies outside it.

Defined in [`engine.paths`](../modules/engine/paths.md).

# Signature

`def repo_relative_path(path: str | Path, root: Path | None) -> str`

# Parameters

| Name | Description |
|---|---|
| `path` | A stored path, usually absolute. |
| `root` | The indexed repository root, or `None` when unknown. |

# Returns

The POSIX-spelled relative path, or `path` unchanged when it is empty or does not sit inside `root`.

# Notes

Path-shape scoring signals (substring and segment matches on the stored
path) must not observe the checkout location: a repository cloned into a
directory named after a query term would otherwise floor every chunk's
score. Callers pass the indexed root so those signals see the same
repo-relative spelling wherever the checkout lives.
