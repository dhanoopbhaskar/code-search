---
type: Module
title: "engine.find_related"
description: "Shared find-related anchor resolution and neighbour ranking for the MCP, CLI, and daemon surfaces."
resource: code_search/engine/find_related.py
tags: [engine, find-related, semantic-search]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/find_related.py
    id: source-code
---

# Overview

Implements the shared `find-related` pipeline used by the MCP tool, the
in-process CLI, and the daemon-forwarded CLI. All three surfaces resolve the
anchor chunk with the same rule — the most specific (smallest) chunk whose
line range contains the requested line — and rank neighbours identically.
The returned payload carries no transport concerns (the MCP server adds
freshness and the daemon wraps it), so `query_time_ms` is the only timing
field produced here.

The anchor chunk's own file is excluded from the neighbour set by default.
When that exclusion leaves no cross-file neighbour the response is labelled
`same_file_only` or `empty` instead of presenting same-file self-chunks as
cross-file relatedness.

# Key Classes

- [`AnchorChunk`](../../types/AnchorChunk.md) — the resolved anchor: stored path, chunk id, FQN, content, language, and line range.

# Key Functions

- [`resolve_anchor_chunk`](../../functions/resolve_anchor_chunk.md) — normalise the caller's path and select the smallest chunk containing the line.
- [`find_related`](../../functions/find_related.md) — embed the anchor, search the vector index, apply boilerplate suppression and semantic reranking, and shape the payload.

# Response Status

| Status | Meaning |
|---|---|
| `cross_file` | At least one neighbour outside the anchor file was found. |
| `same_file_only` | Cross-file exclusion left no neighbour; the best same-file chunk is returned with an explanation. |
| `best_effort` | Only boilerplate-shape content is similar; the best match is returned with an explanation. |
| `empty` | No neighbour is available (empty index, single-chunk index, or no similar content). |

# Internal Helpers

`_build_results` resolves each scored chunk to a result row and applies the
boilerplate exclusion/down-weight; `_best_effort` shapes the explicitly
labelled fallback payload.
