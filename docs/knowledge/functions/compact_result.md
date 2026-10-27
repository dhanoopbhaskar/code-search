---
type: Function
title: "compact_result"
description: "Return a trimmed, agent-sized version of a search result."
resource: code_search/engine/response_service.py#compact_result
tags: [response, output, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/response_service.py
    id: source-code
---

# Overview

Rebuilds a search result from the fixed `_COMPACT_RESULT_FIELDS` allow-list,
dropping the score breakdown and per-arm scores. It keeps the identifiers and
location, at most *max_snippet_lines* lines of content, and the first
non-empty line as `signature` (truncated to `_SIGNATURE_MAX_CHARS` = 200).
The original line range is preserved so a caller can still read the full
block. `fqn` is shortened to the trailing symbol name, and empty optional
fields are omitted. *max_snippet_lines* `0` returns no content;
*paths_only* returns just location and classification fields. Defined in
[`engine.response_service`](../modules/engine/response_service.md).

# Signature

`def compact_result(result: dict[str, Any], max_snippet_lines: int = 10, paths_only: bool = False) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `result` | `dict[str, Any]` | A ranked search result. |
| `max_snippet_lines` | `int` | Maximum content lines to keep; `0` returns no content. |
| `paths_only` | `bool` | Return only location and classification fields. |

# Returns

A new result dict holding the compact fields plus `content`, `signature`, and
`content_truncated`, with empty optional fields removed.
