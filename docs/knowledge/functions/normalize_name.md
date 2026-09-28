---
type: Function
title: "normalize_name"
description: "Casefold and strip separators for comparison."
resource: src/engine/match_boost.py#normalize_name
tags: [ranking, match-boost, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Casefolds and strips separators (underscores, hyphens, camelCase
boundaries) from a name for normalized comparison. Defined in
[`engine.match_boost`](/modules/engine/match_boost.md).

# Signature

`def normalize_name(name: str) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `name` | `str` | The raw identifier or filename to normalize. |

# Returns

The normalized, comparison-ready string.
