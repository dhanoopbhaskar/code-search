---
type: Class
title: "ConfidenceMatchEvidence"
description: "Per-result facts used for confidence computation (confidence.py's MatchEvidence, renamed here to avoid collision)."
resource: src/engine/confidence.py#MatchEvidence
tags: [confidence, ranking, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/confidence.py
    id: source-code
---

# Overview

Per-result facts used to compute a confidence score, paired with
[`QueryMatchContext`](/types/QueryMatchContext.md). Defined in
[`engine.confidence`](/modules/engine/confidence.md) as `MatchEvidence`.

> **Naming note:** The source class is named `MatchEvidence`, identical to
> an unrelated class in `match_boost.py` (see
> [`MatchEvidence`](/types/MatchEvidence.md)). This concept file is named
> `ConfidenceMatchEvidence` only to avoid a filename collision in this flat
> `types/` directory; the class itself is still called `MatchEvidence` in
> code.

# Schema

| Field | Type | Description |
|---|---|---|
| `bm25_score` | `float` | Raw BM25 score for this result. |
| `vector_score` | `float` | Raw vector similarity score for this result. |
| `coverage` | `float` | Query-token coverage for this result. |
