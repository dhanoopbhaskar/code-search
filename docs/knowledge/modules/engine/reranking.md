---
type: Module
title: "engine.reranking"
description: "Post-retrieval result reranking: definition/identifier/config-key boosts, canonicality tiers, corpus-hygiene penalties, and session weighting."
resource: code_search/engine/reranking.py
tags: [engine, ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/reranking.py
    id: source-code
---

# Overview

Result reranking scoring pipeline executed after initial BM25 + vector
hybrid retrieval. Boosts definitions, separates identifier declarations
from usages, lifts config keys, penalises test files, applies session
weights, detects query intent (definition/behavior/authorization), and
applies role/path-class penalties (model/DTO/assembler/exception/infra file
roles, plus DTS/barrel path classes). Final scores are lower-bounded at
`0.0` but not upper-capped, because a fused score above `1.0` is a
legitimate strong match.

Under a docs-intent query, [`documentation_tier`](../../functions/documentation_tier.md)
boosts project docs and penalises third-party and generated pages. Under a
config-intent query, [`config_tier`](../../functions/config_tier.md) boosts
primary application configuration and demotes test/sample/generated
variants. Two corpus-hygiene multipliers demote minified bundles
(`.min.js`/`.min.css`, `/dist/`) and vendored web assets
(`node_modules`, `vendor`, `bower_components`), and a module-cohesion boost
prefers results whose path segment exactly matches a query term (for
example `spring-kafka` over `spring-kafka-2`).

# Key Classes

- [`Reranker`](../../types/Reranker.md) — adjusts raw search scores using definition, identifier-definition, config-key, and session weights alongside test-file and path-class penalties.

# Key Functions

- [`demote_test_file_candidates`](../../functions/demote_test_file_candidates.md) — demote test-file chunks inside the candidate pool before fusion.

# Internal Helpers

`_fqn_matches` checks whether an FQN references any queried symbol
fragment.
