---
type: Class
title: "FileRole"
description: "StrEnum classifying a file's structural role for ranking adjustment (model, dto, exception, infra, dts, barrel, etc.)."
resource: src/engine/classification.py#FileRole
tags: [classification, ranking, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

`StrEnum` classifying a file's structural role for ranking-penalty
purposes (e.g. `MODEL`, `DTO`, `EXCEPTION`, `INFRA`, `DTS`, `BARREL`).
Defined in
[`engine.classification`](/modules/engine/classification.md); consumed by
[`file_role.classify_file_role`](/functions/classify_file_role.md) and the
[`Reranker`](/types/Reranker.md).
