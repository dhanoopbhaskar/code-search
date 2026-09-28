---
type: Class
title: "Settings"
description: "Central configuration dataclass with 150+ CODE_SEARCH_* environment-variable-backed fields."
resource: src/engine/config.py#Settings
tags: [config, settings, dataclass]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/config.py
    id: source-code
---

# Overview

Central configuration dataclass with 150+ fields, each overridable via a
`CODE_SEARCH_*` environment variable. Loaded once via `Settings.load()`
and threaded through nearly every engine component. Defined in
[`engine.config`](/modules/engine/config.md). The full field list is
documented in [config/environment.md](/config/environment.md); this
concept summarises the major field groups.

# Schema (representative groups)

| Group | Example fields | Description |
|---|---|---|
| Core paths | `index_dir`, `repo_root`, `models_dir` | Filesystem locations for index/model storage. |
| Embedding model | `embedding_model_name`, `embedding_dim`, `embedding_batch_size` | Model2Vec embedding configuration. |
| BM25 / lexical search | `bm25_k1`, `bm25_b`, `fts_tokenizer` | FTS5 BM25 tuning parameters. |
| Ranking / fusion | `rrf_k`, `alpha_default`, `rerank_*` | Hybrid fusion and reranking weights. |
| Query gates | `quality_gate_*`, `rescue_*` | Thresholds for the quality gate and rescue ladder. |
| Trust signals | `confidence_*`, `match_boost_*` | Confidence scoring and match-boost thresholds. |
| Session | `session_decay_*` | Session-based personalisation decay parameters. |
| Compliance | `air_gap_enabled`, `redaction_enabled` | Security/compliance toggles. |

# Methods

| Method | Description |
|---|---|
| `load(cls) -> Settings` | Classmethod: construct `Settings` by reading all `CODE_SEARCH_*` environment variables, falling back to defaults. |
