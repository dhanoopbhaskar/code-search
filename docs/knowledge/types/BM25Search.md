---
type: Class
title: "BM25Search"
description: "FTS5-based BM25 keyword search over the indexed code_chunks corpus."
resource: code_search/engine/search.py#BM25Search
tags: [search, bm25, lexical]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/search.py
    id: source-code
---

# Overview

FTS5-based BM25 keyword search over the indexed `code_chunks` corpus.
Uses SQLite FTS5 `bm25()` ranking directly. Defined in
[`engine.search`](../modules/engine/search.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, settings: Settings \| None = None, filter_stopwords: bool = False) -> None` | Initialize the FTS5-backed keyword search over *db*. |
| `invalidate_corpus() -> None` | Drop cached corpus statistics so they are recomputed on next use. |
| `informative_tokens(query: str) -> list[str]` | Return the query's informative sub-words (coverage signal). |
| `concept_subwords(query: str) -> list[str]` | Return the query's candidate concept sub-words (coverage denominator). |
| `search(query: str, top_k: int = 10, content: str = 'all') -> list[tuple[int, float]]` | Run FTS5 BM25 search, returning `(chunk_rowid, score)` pairs. |
| `count(query: str) -> int` | Return the number of FTS5-matching chunks for *query* (uncapped). |
