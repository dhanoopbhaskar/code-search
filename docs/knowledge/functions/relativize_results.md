---
type: Function
title: "relativize_results"
description: "Return results with file_path/fqn relative to the index root."
resource: code_search/engine/response_service.py#relativize_results
tags: [response, output, paths, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-21T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/response_service.py
    id: source-code
---

# Overview

Rewrites each result's `file_path` and `fqn` relative to the indexed root so
machine-readable output does not expose the filesystem layout. Stored `fqn`
values carry an absolute path prefix (`<abs path>::<declaration>`), so the
prefix is stripped as well. A falsy *root* leaves the results unchanged.
Input results are not mutated. Defined in
[`engine.response_service`](../modules/engine/response_service.md).

# Signature

`def relativize_results(results: list[dict[str, Any]], root: str | Path | None) -> list[dict[str, Any]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `results` | `list[dict[str, Any]]` | Search results to rewrite (not mutated). |
| `root` | `str \| Path \| None` | The indexed repository root; `None` leaves paths unchanged. |

# Returns

Copies of the results with portable, root-relative path spellings.
