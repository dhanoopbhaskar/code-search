---
type: Module
title: "engine.confidence"
description: "Per-result search confidence calibration with match-type evidence (definition boosts, exact-match floors, ambiguity cap)."
resource: src/engine/confidence.py
tags: [engine, ranking, confidence]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Per-result search confidence calibration with match-type evidence. A base
blend scores query sub-word presence in chunk identifiers blended with
vector cosine, then layers match-type evidence on top: primary-definition
and controller-endpoint boosts, evidence floors for exact FQN/symbol
matches, an ambiguity cap for overloaded names, and a semantic-only floor
for strong vector matches with no lexical overlap. Pure, deterministic
function of query text, chunk metadata, and raw vector cosine.

# Key Constants

`BOOST_DEFINITION = 0.15`, `BOOST_CONTROLLER_ENDPOINT = 0.10`,
`FLOOR_EXACT_FQN_DEFINITION = 0.90`, `FLOOR_EXACT_FQN = 0.65`,
`FLOOR_EXACT_SYMBOL_DEFINITION = 0.80`, `FLOOR_EXACT_SYMBOL = 0.65`,
`AMBIGUOUS_CAP = 0.69`, `SEMANTIC_ONLY_FLOOR = 0.50`,
`SEMANTIC_ONLY_VECTOR_MIN = 0.50`.

# Key Classes

- [`QueryMatchContext`](/types/QueryMatchContext.md) — query-level facts computed once per request.
- [`ConfidenceMatchEvidence`](/types/ConfidenceMatchEvidence.md) — per-result facts for confidence computation (distinct from `match_boost.MatchEvidence`).

# Key Functions

- [`qualified_query_name`](/functions/qualified_query_name.md), [`is_exact_fqn_match`](/functions/is_exact_fqn_match.md), [`is_exact_symbol_match`](/functions/is_exact_symbol_match.md), [`is_controller_endpoint`](/functions/is_controller_endpoint.md) — evidence classifiers.
- [`subword_overlap`](/functions/subword_overlap.md), [`confidence_score`](/functions/confidence_score.md) — base lexical/vector blend.
- [`calibrated_confidence`](/functions/calibrated_confidence.md) — full calibrated confidence for one candidate.
- [`confidence_band`](/functions/confidence_band.md), [`is_borderline`](/functions/is_borderline.md), [`envelope_band`](/functions/envelope_band.md) — banding and envelope aggregation.
