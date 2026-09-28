---
type: Module
title: "engine.occurrence_count"
description: "Per-line occurrence counting for exhaustive search mode, verifiable against a grep ground-truth oracle."
resource: src/engine/occurrence_count.py
tags: [engine, search, exhaustive-mode]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/occurrence_count.py
    id: source-code
---

# Overview

Provides per-line occurrence counting for exhaustive mode. Returns
per-line counts where the total equals the sum of the per-line array,
enabling verification against a grep ground-truth oracle.

# Key Functions

- [`count_occurrences_per_line`](/functions/count_occurrences_per_line.md) — count occurrences of a pattern per line in text.
