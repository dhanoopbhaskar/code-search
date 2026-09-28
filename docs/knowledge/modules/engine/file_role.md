---
type: Module
title: "engine.file_role"
description: "File role classification with evidence-based overrides (e.g., promoting infra files carrying DB connection strings)."
resource: src/engine/file_role.py
tags: [engine, ranking, classification]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/file_role.py
    id: source-code
---

# Overview

Manages file role classification for ranking adjustments. Classifies
files (infra, config, docs, code, etc.) and applies evidence-based
overrides to promote infrastructure files containing database
connections or other meaningful content. Returns metadata about canonical
and inferred file extensions for each role.

# Key Functions

- [`classify_file_role`](/functions/classify_file_role.md) — classify a file's role for ranking adjustment, with evidence-based overrides.
