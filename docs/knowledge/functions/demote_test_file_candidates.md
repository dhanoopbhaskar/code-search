---
type: Function
title: "demote_test_file_candidates"
description: "Demote test-file chunks inside the candidate pool before fusion."
resource: src/engine/reranking.py#demote_test_file_candidates
tags: [ranking, reranking, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/reranking.py
    id: source-code
---

# Overview

Demotes test-file chunks inside the candidate pool before RRF fusion,
unless `include_tests` is requested. Defined in
[`engine.reranking`](/modules/engine/reranking.md); invoked from
[`HybridSearch`](/types/HybridSearch.md)'s internal pipeline.

# Signature

`def demote_test_file_candidates(candidates: list[dict[str, Any]], include_tests: bool) -> list[dict[str, Any]]`

# Parameters

| Name | Type | Description |
|---|---|---|
| `candidates` | `list[dict[str, Any]]` | The candidate pool prior to fusion. |
| `include_tests` | `bool` | Whether test files should be included without demotion. |

# Returns

The candidate pool with test-file chunks demoted (if applicable).
