---
type: Module
title: "engine.rescue_floor"
description: "Lexical relevance threshold for the rescue tier, distinguishing gibberish queries from borderline-real ones."
resource: src/engine/rescue_floor.py
tags: [engine, ranking, rescue]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/rescue_floor.py
    id: source-code
---

# Overview

Defines the lexical relevance threshold for the rescue tier, ensuring
pure-gibberish queries return `no_match` while borderline queries still
return results. Gates the rescue tier based on meaningful token overlap
with indexed content.

# Key Constants

`DEFAULT_LEXICAL_THRESHOLD = 0.15`, `DEFAULT_PURE_GIBBERISH_NO_MATCH =
True`, `DEFAULT_BORDERLINE_REAL_ALLOWED = True`.

# Key Functions

- [`evaluate_rescue_floor`](/functions/evaluate_rescue_floor.md) — evaluate whether the rescue tier should return results.
