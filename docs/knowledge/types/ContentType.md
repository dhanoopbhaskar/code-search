---
type: Class
title: "ContentType"
description: "StrEnum for the content axis a chunk belongs to (code, docs, config, test)."
resource: src/engine/classification.py#ContentType
tags: [classification, content-axis, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

`StrEnum` for the content axis a chunk belongs to: code, documentation,
configuration, or test. Defined in
[`engine.classification`](/modules/engine/classification.md); used to
scope search queries via the `content` parameter (see
[`HybridSearch.search`](/types/HybridSearch.md)).
