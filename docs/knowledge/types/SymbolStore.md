---
type: Class
title: "SymbolStore"
description: "SQLite-backed CRUD, resolution, and lookup for symbol records."
resource: src/engine/symbols.py#SymbolStore
tags: [symbols, storage, resolution]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/symbols.py
    id: source-code
---

# Overview

SQLite-backed CRUD operations for symbol records, providing resolution
and lookup capabilities. Defined in
[`engine.symbols`](/modules/engine/symbols.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, db: GraphDatabase, settings: Settings \| None = None) -> None` | Initialize store over a graph database. |
| `insert_symbol(self, symbol: dict[str, Any]) -> int \| None` | Insert a single symbol, resolving parent FQN; returns new `symbols.id` or `None`. |
| `insert_symbols_batch(self, symbols: list[dict[str, Any]]) -> dict[str, int]` | Batch-insert symbols with optimized parent lookups; returns `{fqn: db_id}`. |
| `resolve_name(self, query: str, max_candidates: int \| None = None) -> dict[str, Any]` | Resolve query to a resolution envelope `{kind, symbol, candidates, overloads, ambiguous, outcome}`. |
| `resolve_symbol(self, query: str) -> tuple[dict[str, Any] \| None, list[dict[str, Any]]]` | Thin wrapper returning `(symbol, candidates)` with an ambiguity decision. |
| `lookup_by_fqn(self, fqn: str) -> dict[str, Any] \| None` | Exact FQN lookup, auto-picking the first candidate for ambiguous names. |
| `lookup_by_file(self, file_path: str) -> list[dict[str, Any]]` | Return all symbols declared in a file with exact/suffix/bare-filename fallback. |
| `get_by_id(self, symbol_id: int) -> dict[str, Any] \| None` | Fetch symbol row with parent info and parsed signature. |
| `methods_of(self, parent_symbol_id: int, name: str \| None = None) -> list[dict[str, Any]]` | Return member declarations of a type, optionally filtered by name. |
| `methods_of_many(self, parent_symbol_ids: list[int], name: str \| None = None) -> dict[int, list[dict[str, Any]]]` | Batch query for members of multiple types in one SELECT. |
| `build_symbol_catalog(self) -> dict[str, int]` | Build an in-memory catalog mapping `fqn`/`conventional_fqn` → symbol id. |
