---
type: Class
title: "FileRole"
description: "StrEnum classifying a file's structural role for behavior/definition reranking."
resource: src/engine/classification.py#FileRole
tags: [classification, ranking, enum]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/classification.py
    id: source-code
---

# Overview

`StrEnum` classifying a file's structural role for behavior-intent and
definition reranking: data-flow plumbing (`MODEL`/`DTO`/`ASSEMBLER`/
`EXCEPTION`), deployment files (`INFRA`), config/schema (`CONFIG`),
prose (`DOCS`), analysis artifacts (`ANALYSIS`), and the `CODE` default.
Defined in [`engine.classification`](../modules/engine/classification.md);
consumed by [`Reranker`](Reranker.md).

# Values

| Value | Description |
|---|---|
| `CODE` | Default; ordinary source code. |
| `MODEL` | Data-model / entity plumbing (demoted under behavior-intent queries). |
| `DTO` | Data-transfer plumbing (demoted under behavior-intent queries). |
| `ASSEMBLER` | Mapping/assembler plumbing (demoted under behavior-intent queries). |
| `EXCEPTION` | Exception/error plumbing (demoted under behavior-intent queries). |
| `INFRA` | Deployment and container files (demoted under code-language queries). |
| `CONFIG` | Configuration and schema files (boosted for config/DDL-scent queries). |
| `RESOURCE` | Defined but not currently emitted by `file_role` (data extensions such as `.xml`/`.json`/`.yaml`/`.toml` resolve `CONFIG`). |
| `DOCS` | Prose chunks (content type `docs`). |
| `ANALYSIS` | Repo-local report/analysis artifacts (demoted below shipped content). |
