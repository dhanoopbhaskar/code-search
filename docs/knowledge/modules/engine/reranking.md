---
type: Module
title: "engine.reranking"
description: "Post-retrieval result reranking: definition boost, test-file penalty, session weighting, file-role penalties."
resource: src/engine/reranking.py
tags: [engine, ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/reranking.py
    id: source-code
---

# Overview

Result reranking scoring pipeline executed after initial BM25 + vector
hybrid retrieval. Boosts definitions, penalises test files, applies
session weights, detects query intent (definition/behavior/authorization),
and applies file-role-based penalties (model/DTO/exception/infra/dts
/barrel).

# Key Classes

- [`Reranker`](/types/Reranker.md) — adjusts raw search scores using definition boost, test-file penalty, non-canonical penalty, and session weight.

# Key Functions

- [`demote_test_file_candidates`](/functions/demote_test_file_candidates.md) — demote test-file chunks inside the candidate pool before fusion.

# Internal Helpers

`_fqn_matches` checks whether an FQN references any queried symbol
fragment.
