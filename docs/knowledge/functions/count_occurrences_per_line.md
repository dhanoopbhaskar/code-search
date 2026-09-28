---
type: Function
title: "count_occurrences_per_line"
description: "Count occurrences of a pattern per line in text."
resource: src/engine/occurrence_count.py#count_occurrences_per_line
tags: [search, exhaustive-mode, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/occurrence_count.py
    id: source-code
---

# Overview

Counts occurrences of a pattern per line in text, returning a per-line
array whose sum equals the total match count, enabling verification
against a grep ground-truth oracle in exhaustive mode. Defined in
[`engine.occurrence_count`](/modules/engine/occurrence_count.md).

# Signature

`def count_occurrences_per_line(text: str, pattern: str) -> list[int]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `text` | `str` | The text to search within. |
| `pattern` | `str` | The literal or regex pattern to count. |

# Returns

Per-line occurrence counts, one entry per line in *text*.
