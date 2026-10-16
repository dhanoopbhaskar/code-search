---
type: Module
title: "engine.reranking"
description: "Post-retrieval result reranking: definition boost, test-file penalty, session weighting, file-role penalties."
resource: code_search/engine/reranking.py
tags: [engine, ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/reranking.py
    id: source-code
---

# Overview

Result reranking scoring pipeline executed after initial BM25 + vector
hybrid retrieval. Boosts definitions, penalises test files, applies
session weights, detects query intent (definition/behavior/authorization),
and applies role/path-class penalties (model/DTO/assembler/exception/infra
file roles, plus DTS/barrel path classes).

# Key Classes

- [`Reranker`](../../types/Reranker.md) — adjusts raw search scores using definition boost, test-file penalty, non-canonical penalty, and session weight.

# Key Functions

- [`demote_test_file_candidates`](../../functions/demote_test_file_candidates.md) — demote test-file chunks inside the candidate pool before fusion.

# Internal Helpers

`_fqn_matches` checks whether an FQN references any queried symbol
fragment.
