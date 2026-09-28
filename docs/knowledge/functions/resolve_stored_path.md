---
type: Function
title: "resolve_stored_path"
description: "Return the stored code_chunks.file_path spelling for a candidate path."
resource: src/engine/paths.py#resolve_stored_path
tags: [paths, find-related, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/paths.py
    id: source-code
---

# Overview

Returns the exact stored `code_chunks.file_path` spelling matching a
candidate path, resolving discrepancies between filesystem paths and the
spelling recorded at index time. Defined in
[`engine.paths`](/modules/engine/paths.md); used by the `find_related`
MCP tool.

# Signature

`def resolve_stored_path(db: GraphDatabase, candidate: Path) -> str \| None`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `GraphDatabase` | Graph database to query. |
| `candidate` | `Path` | The normalized candidate path. |

# Returns

The stored path spelling, or `None` if not found in the index.
