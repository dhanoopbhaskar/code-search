---
type: Function
title: "content_type"
description: "Classify a file into the content axis (code, docs, config, test)."
resource: src/engine/classification.py#content_type
tags: [classification, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

Classifies a file into the content axis using extension and path
heuristics. Defined in
[`engine.classification`](/modules/engine/classification.md).

# Signature

`def content_type(file_path: str) -> ContentType`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | Path of the file to classify. |

# Returns

The [`ContentType`](/types/ContentType.md) axis for the file.
