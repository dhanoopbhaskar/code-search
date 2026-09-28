---
type: Module
title: "engine.match_boost"
description: "Pure filename/exact-match classification and bounded boost math for search ranking."
resource: src/engine/match_boost.py
tags: [engine, ranking, match-boost]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/match_boost.py
    id: source-code
---

# Overview

Pure filename/exact-match classification and bounded boost math for
search ranking. Fuses BM25 and vector results via RRF, then layers
additive, pool-max-scaled passes to boost exact matches (filename,
symbol, FQN). Provides pure functions for classification, boost
computation, and verdict generation — all unit-testable without a
database.

# Key Classes

- [`MatchTier`](/types/MatchTier.md) — IntEnum ranking the strength of filename/symbol evidence (`none` .. `exact_fqn`).
- [`QueryNameContext`](/types/QueryNameContext.md) — request-scoped name facts computed once and reused per candidate.
- [`MatchEvidence`](/types/MatchEvidence.md) — per-candidate facts a boost verdict is derived from.
- [`BoostVerdict`](/types/BoostVerdict.md) — the additive ranking adjustment for one candidate.

# Key Functions

- [`normalize_name`](/functions/normalize_name.md) — casefold and strip separators for comparison.
- [`boost_for_tier`](/functions/boost_for_tier.md) — bounded additive boost for a match tier.
- [`strongest_tier`](/functions/strongest_tier.md) — highest-priority tier in an iterable.
- [`compute_verdict`](/functions/compute_verdict.md) — bounded boost verdict for one candidate.
- [`classify_filename_match`](/functions/classify_filename_match.md), [`classify_symbol_match`](/functions/classify_symbol_match.md), [`classify_path_match`](/functions/classify_path_match.md) — per-signal classifiers.
- [`filename_candidates`](/functions/filename_candidates.md) — chunk ids whose file name/stem equals the query.
