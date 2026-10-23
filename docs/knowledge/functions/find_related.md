---
type: Function
title: "find_related"
description: "Rank the chunks most related to a file/line anchor via the vector index."
resource: code_search/engine/find_related.py#find_related
tags: [find-related, function, semantic-search]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/find_related.py
    id: source-code
---

# Overview

Embeds the anchor chunk, queries the vector index for nearest neighbours,
applies directional boilerplate suppression and optional semantic reranking,
and returns a transport-neutral payload. Shared by the MCP tool, the CLI,
and the daemon so all surfaces rank related chunks identically. Defined in
[`engine.find_related`](../modules/engine/find_related.md).

# Signature

`def find_related(comps: dict[str, Any], file_path: str, line_number: int, limit: int) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `comps` | `dict[str, Any]` | The shared component registry (`db`, `metadata`, `embedding_gen`, `vector_index`, `context_dir`, and optional `settings`/`redactor`). |
| `file_path` | `str` | Absolute or project-relative path to a file. |
| `line_number` | `int` | Line within the file to anchor. |
| `limit` | `int` | Maximum related chunks to return; capped at `find_related_limit`. |

# Returns

A payload with `results` (anchor excluded), `vector_health`, `status`
(`cross_file`/`same_file_only`/`best_effort`/`empty`), and `query_time_ms` —
or an `error` payload when no indexed chunk contains the line.
