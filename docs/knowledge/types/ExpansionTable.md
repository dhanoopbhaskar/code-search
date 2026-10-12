---
type: Class
title: "ExpansionTable"
description: "Two-way, case-insensitive acronym/phrase to expansion-terms table with fuzzy matching."
resource: src/engine/expansions.py#ExpansionTable
tags: [query-analysis, expansion]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/expansions.py
    id: source-code
---

# Overview

Two-way, case-insensitive acronym/phrase → expansion-terms table with
fuzzy matching, seeded from `_BUILTIN_EXPANSIONS` plus an optional JSON
overlay. Defined in
[`engine.expansions`](../modules/engine/expansions.md); consumed by
[`analyze_query`](../functions/analyze_query.md).

# Methods

| Method | Description |
|---|---|
| `__init__(config_path: str \| None = None) -> None` | Create an expansion table, optionally merging a user JSON file. |
| `expand(query: str) -> set[str]` | Return the query plus any expansion terms reachable from it. |
| `matched_phrases(query: str) -> list[str]` | Return the table keys that fuzzy-match inside *query*, longest first. |
| `expanded_text(query: str) -> str` | Return *query* with expansion terms appended (FTS + embedding input). |
