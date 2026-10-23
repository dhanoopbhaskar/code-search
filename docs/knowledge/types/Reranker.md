---
type: Class
title: "Reranker"
description: "Adjusts raw search scores using definition/identifier/config-key boosts, canonicality tiers, corpus-hygiene penalties, and session weighting."
resource: code_search/engine/reranking.py#Reranker
tags: [ranking, reranking]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-23T08:32:00Z }
status: draft
sources:
  - resource: code_search/engine/reranking.py
    id: source-code
---

# Overview

Adjusts raw fused search scores using a definition boost, an
identifier-definition boost, a config-key boost, a docs-content boost, a
test-file penalty, a non-canonical-path penalty, file-role penalties, and
session weighting (via [`SessionDatabase`](SessionDatabase.md)). Final scores
are lower-bounded at `0.0` but deliberately **not** upper-capped: a fused
score legitimately exceeds `1.0` for strong matches, and clamping collapsed
every strong candidate to `1.00`. Defined in
[`engine.reranking`](../modules/engine/reranking.md).

Identifier signals separate declarations from references: the definition of
the identifier a query names (recognised by
[`query_symbol_identifier`](../functions/query_symbol_identifier.md) or a
dotted/`::` config key) is boosted, and chunks that merely mention that
identifier are demoted — but only when the definition is present in the
candidate pool, so a usage-only answer is never penalised into nothing.

Two content-axis tints apply the canonicality classifiers: docs-intent
queries use `documentation_tier` (project boost, third-party/generated
penalties) and config-intent queries use `config_tier` (primary boost,
non-primary penalty). Corpus-hygiene multipliers demote minified bundles
and vendored web assets, and a module-cohesion boost prefers results whose
path segment exactly matches a query term.

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, session_db: SessionDatabase \| None = None, settings: Settings \| None = None) -> None` | Create a reranker wired to the graph and session databases. |
| `rerank(results: list[dict[str, Any]], query_terms: list[str] \| None = None, query: str \| None = None) -> list[dict[str, Any]]` | Reorder *results* in place by applying the definition, definition-owner, identifier-definition, config-key, docs-content, canonicality-tier, module-cohesion, file-role, and authorization boosts; the usage, test-file, DTS/barrel, non-canonical, minified, and vendor penalties; and session weighting. Each result gains `session_weight`. |
