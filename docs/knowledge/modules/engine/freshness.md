---
type: Module
title: "engine.freshness"
description: "Computes index-freshness signals via stat fast-path baselines and self-healing re-hash on change."
resource: src/engine/freshness.py
tags: [engine, freshness, staleness]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/freshness.py
    id: source-code
---

# Overview

Computes index-freshness signals to answer "is the working tree ahead of
the index?" via a two-tier detection system combining a stat fast-path
(file size/mtime matching skips rehashing) and re-hash on stat change
(with self-healing for mtime-only touches). Tracks deleted/new/modified
files and caches the signal under index metadata with a TTL.

# Key Classes

- [`FreshnessChecker`](/types/FreshnessChecker.md) — computes a working-tree-vs-index staleness signal via stat baselines and optional rehashing.

# Internal Helpers

`_now_iso`/`_parse_iso` handle the ISO timestamp format shared with the
metadata store.
