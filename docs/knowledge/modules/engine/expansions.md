---
type: Module
title: "engine.expansions"
description: "Static query-expansion table mapping acronyms/paraphrases to code vocabulary."
resource: src/engine/expansions.py
tags: [engine, query-analysis, expansion]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/expansions.py
    id: source-code
---

# Overview

Static query-expansion table for acronym/paraphrase → code vocabulary
mapping. Seeded with built-in expansions (e.g., `cors` → `cross origin`),
with an optional JSON file overlay for user customizations. Air-gap
safe — no network, no learning, deterministic. Expansion is recall-only:
wrong expansions cannot produce confident false positives because
downstream gates still apply.

# Key Constants

`_BUILTIN_EXPANSIONS` — dict of 20+ acronym/phrase pairs mapped to domain
vocabulary.

# Key Classes

- [`ExpansionTable`](/types/ExpansionTable.md) — two-way, case-insensitive acronym/phrase → expansion-terms table with fuzzy matching.
