---
type: Class
title: "ContentType"
description: "StrEnum for the content axis an indexed chunk belongs to (code, config, docs)."
resource: src/engine/classification.py#ContentType
tags: [classification, content-axis, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

`StrEnum` giving the content axis of an indexed chunk: `CODE`
(language-parseable source), `CONFIG` (configuration and resource
data), or `DOCS` (prose). Defined in
[`engine.classification`](../modules/engine/classification.md); shared
by the indexer, the ranking weight lookup, and the content filter.

# Values

| Value | Description |
|---|---|
| `CODE` | Language-parseable source code. |
| `CONFIG` | Configuration and resource data (properties/YAML/TOML/JSON/XML/`.conf`/`.gradle`/env-style). |
| `DOCS` | Prose files (markdown/`.rst`/`.txt`). |
