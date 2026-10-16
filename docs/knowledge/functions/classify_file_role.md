---
type: Function
title: "classify_file_role"
description: "Classify a file's role for ranking adjustment, with evidence-based overrides."
resource: code_search/engine/file_role.py#classify_file_role
tags: [ranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/file_role.py
    id: source-code
---

# Overview

Classifies a file's role for ranking adjustment, applying evidence-based
overrides (e.g. promoting infra files that carry DB connection strings).
Defined in [`engine.file_role`](../modules/engine/file_role.md); wraps
[`classification.file_role`](file_role.md) with content-aware
overrides.

# Signature

`def classify_file_role(file_path: str, content_patterns: list[str] \| None = None, literal_evidence: list[str] \| None = None) -> dict[str, Any]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `file_path` | `str` | Absolute path to the file |
| `content_patterns` | `list[str] \| None` | Inferred content patterns from AST analysis |
| `literal_evidence` | `list[str] \| None` | Literal dependency strings found in the file |

# Returns

dict with keys: - role (FileRole): The classified role - evidence_threshold (int): Minimum literal evidence required to override - canonical_extensions (set): File extensions considered canonical for this role - inferred_extensions (set): File extensions inferred from content patterns
