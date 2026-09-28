---
type: Overview
title: "Design Patterns"
description: "Recurring architectural patterns used throughout the code-search engine."
resource: src/
tags: [architecture, design-patterns]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/
    id: source-code
---

# Overview

Recurring architectural and implementation patterns observed across the
`code-search` engine.

# Quality-Gate + Rescue-Ladder Pattern

Used in [`HybridSearch`](/types/HybridSearch.md)
([`engine.search`](/modules/engine/search.md)). Rather than always
returning the top-k fused results, the pipeline runs fused results through
a multi-signal quality gate (confidence, lexical coverage, rescue-floor
checks). If the gate fails, progressively looser "rescue" tiers
(`_rescue_t1`, `_rescue_t2`) attempt to recover a reasonable answer before
falling back to an explicit `no_match` envelope — preferring an honest "no
result" over a low-confidence false positive.

# Bounded, Evidence-Based Boosting

Used in [`match_boost.py`](/modules/engine/match_boost.md) and
[`confidence.py`](/modules/engine/confidence.md). Rather than
unboundedly rewarding partial matches, every boost
([`BoostVerdict`](/types/BoostVerdict.md),
[`calibrated_confidence`](/functions/calibrated_confidence.md)) is
capped and requires concrete evidence (exact FQN match, exact symbol
match, controller-endpoint markers) — preventing runaway score inflation
from weak heuristics.

# Pure-Function Signal Computation

Signal-computation modules (
[`semantic_signals.py`](/modules/engine/semantic_signals.md),
[`embed_representation.py`](/modules/engine/embed_representation.md),
[`scent_detection.py`](/modules/engine/scent_detection.md),
[`rescue_floor.py`](/modules/engine/rescue_floor.md)) are written as pure
functions with no I/O, network, or global mutable state — enabling
fast, deterministic unit testing and air-gap safety by construction.

# StrEnum Classification Axes

Multiple independent classification axes are modeled as `StrEnum`s rather
than booleans or strings: [`ContentType`](/types/ContentType.md) (code
axis), [`FileRole`](/types/FileRole.md) (structural role),
[`PathClass`](/types/PathClass.md) (path category),
[`ContentIntent`](/types/ContentIntent.md) (query intent),
[`MatchTier`](/types/MatchTier.md) (match strength). Keeping these
orthogonal avoids combinatorial special-casing in the ranking pipeline.

# Two-Tier Freshness Detection

[`FreshnessChecker`](/types/FreshnessChecker.md) combines a cheap stat
fast-path (file size/mtime comparison) with a self-healing re-hash
fallback triggered only when stats disagree — avoiding full-corpus
rehashing on every incremental index run while still catching
mtime-only touches (e.g. from `git checkout`).

# Air-Gap-by-Default Compliance

[`redactor.py`](/modules/engine/redactor.md) monkey-patches `socket` to
block all outbound connections by default
([`air_gap_enforcement`](/functions/air_gap_enforcement.md)), with a
narrow, explicit escape hatch
([`allow_downloads`](/functions/allow_downloads.md)) only for the
`download-models` CLI command — making network access an opt-in
exception rather than the default.

# See Also

- [System Overview](/architecture/system-overview.md)
