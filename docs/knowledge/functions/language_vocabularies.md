---
type: Function
title: "language_vocabularies"
description: "Map each indexed language to its exact sub-word set."
resource: src/engine/language.py#language_vocabularies
tags: [language, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/language.py
    id: source-code
---

# Overview

Maps each indexed language to its exact sub-word vocabulary set, built
from the corpus, used for language inference and coverage computation.
Defined in [`engine.language`](/modules/engine/language.md).

# Signature

`def language_vocabularies(db: GraphDatabase) -> dict[str, set[str]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `db` | `GraphDatabase` | The graph database to scan for corpus vocabulary. |

# Returns

Mapping of language name to its exact sub-word set.
