---
type: Overview
title: "Design Patterns"
description: "Recurring architectural patterns used throughout the code-search engine."
resource: code_search/
tags: [architecture, design-patterns]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/
    id: source-code
---

# Overview

Recurring architectural and implementation patterns observed across the
`code-search` engine.

# Quality-Gate + Rescue-Ladder Pattern

Used in [`HybridSearch`](../types/HybridSearch.md)
([`engine.search`](../modules/engine/search.md)). Rather than always
returning the top-k fused results, the pipeline runs the raw BM25/vector
retrieval evidence through a multi-signal quality gate (informative-token
coverage, concept signal, exact-token coverage, and top-vector floors)
before fusion. If the gate fails,
progressively looser "rescue" tiers (`_rescue_t1`, `_rescue_t2`) attempt
to recover a reasonable answer before
falling back to an explicit `no_match` envelope — preferring an honest "no
result" over a low-confidence false positive.

# Intent-Scoped Retrieval

Used in [`HybridSearch`](../types/HybridSearch.md) and
[`classify_content_intent`](../functions/classify_content_intent.md). The
content scope is inferred from the query shape rather than fixed, so a
code-shaped query searches source first, a docs-shaped query widens to all
content, and a neutral query uses `code_focused`. The same intent machinery
separates declarations from mentions: identifier/config-key queries lift the
definition and only demote usages when the definition is present, and
constant-shaped queries lift constant declarations over similarly named
accessors. Every lift remains a bounded, evidence-backed boost.

# Bounded, Evidence-Based Boosting

Used in [`match_boost.py`](../modules/engine/match_boost.md) and
[`confidence.py`](../modules/engine/confidence.md). Rather than
unboundedly rewarding partial matches, every boost
([`BoostVerdict`](../types/BoostVerdict.md),
[`calibrated_confidence`](../functions/calibrated_confidence.md)) is
capped and requires concrete evidence (exact FQN match, exact symbol
match, controller-endpoint markers) — preventing runaway score inflation
from weak heuristics.

# Pure-Function Signal Computation

Signal-computation modules such as
[`embed_representation.py`](../modules/engine/embed_representation.md),
[`scent_detection.py`](../modules/engine/scent_detection.md), and
[`rescue_floor.py`](../modules/engine/rescue_floor.md) are written as pure
functions with no I/O, network, or global mutable state — enabling fast,
deterministic unit testing and air-gap safety by construction.
[`semantic_signals.py`](../modules/engine/semantic_signals.md) is likewise
free of global mutable state, but reads the call graph from the
[`GraphDatabase`](../types/GraphDatabase.md) passed into each call rather
than holding a connection itself.

# StrEnum Classification Axes

Multiple independent classification axes are modeled as enums rather
than booleans or strings: [`ContentType`](../types/ContentType.md) (code
axis), [`FileRole`](../types/FileRole.md) (structural role),
[`PathClass`](../types/PathClass.md) (path category), and
[`ContentIntent`](../types/ContentIntent.md) (query intent) are
`StrEnum`s; [`MatchTier`](../types/MatchTier.md) (match strength) is an
`IntEnum` whose integer values encode priority. Keeping these orthogonal
avoids combinatorial special-casing in the ranking pipeline.

# Two-Tier Freshness Detection

[`FreshnessChecker`](../types/FreshnessChecker.md) combines a cheap stat
fast-path (file size/mtime comparison) with a self-healing re-hash
fallback triggered only when stats disagree — avoiding full-corpus
rehashing on every incremental index run while still catching
mtime-only touches (e.g. from `git checkout`).

# One Rule, Many Surfaces

Several retrieval rules exist exactly once and are called from the CLI, the
daemon, and the MCP server: `SymbolStore.resolve_name` for name resolution,
`EdgeStore.get_call_graph_page` for call-graph paging,
[`find_implementations`](../functions/find_implementations.md) for interface
lookup, `HybridSearch.search` for ranking, and
[`engine.graph_surface`](../modules/engine/graph_surface.md)'s payload builders
for discovery. Transport layers add only freshness signals, audit entries, and
rendering, which is why `ask`
([`engine.ask`](../modules/engine/ask.md)) can delegate rather than reimplement
and cannot disagree with the dedicated surface for the same request.

# Bounded, Generation-Keyed Caching

[`AdjacencyCache`](../types/AdjacencyCache.md) is the general shape of an
in-process cache here: the key includes the published `index_generation`, a
committed write invalidates it eagerly, an entry above the byte budget is
refused rather than kept, and idle entries expire. Crucially the cache is
**best effort** — every consumer (traversal, paging cursors, Cypher) has a SQL
path, so a cache failure degrades latency, never correctness.

# Explicit Evidence Boundaries

Answers carry their own limits instead of implying more than the index knows:
`check_index_coverage` separates `no_recorded_issue` from
`not_indexed`/`skipped`/`excluded`; `find_dead_code` reports unresolved
same-name references and test-only usage per row; Cypher results state that
"absence is not proof of completeness"; and an unsupported Cypher construct or
architecture aspect returns an error rather than an empty result. The same
posture appears in search as `strict` abstention and `budget_exceeded`.

# Air-Gap-by-Default Compliance

[`redactor.py`](../modules/engine/redactor.md) monkey-patches `socket` to
block all outbound connections by default
([`air_gap_enforcement`](../functions/air_gap_enforcement.md)), with a
narrow, explicit escape hatch
([`allow_downloads`](../functions/allow_downloads.md)) used only for
explicit model downloads (`download-models`, and the interactive prompt in
`index`) — making network access an opt-in exception rather than the
default.

# See Also

- [System Overview](system-overview.md)
