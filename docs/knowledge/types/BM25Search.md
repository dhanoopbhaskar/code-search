---
type: Class
title: "BM25Search"
description: "FTS5-based BM25 keyword search over the indexed code_chunks corpus."
resource: src/engine/search.py#BM25Search
tags: [search, bm25, lexical]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/search.py
    id: source-code
---

# Overview

FTS5-based BM25 keyword search over the indexed `code_chunks` corpus.
Uses SQLite FTS5 `bm25()` ranking directly. Defined in
[`engine.search`](/modules/engine/search.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, db, settings=None, filter_stopwords=False) -> None` | Initialize the FTS5-backed keyword search. |
| `invalidate_corpus() -> None` | Drop cached corpus statistics so they recompute on next use. |
| `informative_tokens(self, query: str) -> list[str]` | Return the query's informative sub-words (coverage signal). |
| `concept_subwords(self, query: str) -> list[str]` | Return the query's candidate concept sub-words (coverage denominator). |
| `search(self, query: str, top_k: int = 10, content: str = "all") -> list[tuple[int, float]]` | Run FTS5 BM25 search, returning `(chunk_rowid, score)` pairs. |
| `count(self, query: str) -> int` | Return the number of FTS5-matching chunks for *query* (uncapped). |
