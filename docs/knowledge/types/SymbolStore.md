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
[`engine.symbols`](../modules/engine/symbols.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db: GraphDatabase, settings: Settings \| None = None) -> None` | Initialize the symbol store over a graph database. |
| `insert_symbol(symbol: dict[str, Any]) -> int \| None` | Insert a single symbol record, linking to its parent. |
| `insert_symbols_batch(symbols: list[dict[str, Any]]) -> dict[str, int]` | Insert a batch of symbols, returning `{fqn: db_id}` map. |
| `resolve_name(query: str, max_candidates: int \| None = None) -> dict[str, Any]` | Resolve *query* to a resolution envelope (the ONE shared rule). |
| `resolve_symbol(query: str) -> tuple[dict[str, Any] \| None, list[dict[str, Any]]]` | Resolve *query* to `(symbol, candidates)`. |
| `lookup_by_fqn(fqn: str) -> dict[str, Any] \| None` | Look up a symbol by FQN, auto-picking the first candidate. |
| `lookup_by_file(file_path: str) -> list[dict[str, Any]]` | Return all symbols declared in *file_path*. |
| `get_by_id(symbol_id: int) -> dict[str, Any] \| None` | Return the symbol row for *symbol_id*, or `None`. |
| `methods_of(parent_symbol_id: int, name: str \| None = None) -> list[dict[str, Any]]` | Return the member declarations of type *parent_symbol_id*. |
| `methods_of_many(parent_symbol_ids: list[int], name: str \| None = None) -> dict[int, list[dict[str, Any]]]` | Return member declarations for many parent types in one query. |
| `build_symbol_catalog() -> dict[str, int]` | Query all symbols and build in-memory catalog: fqn/conventional_fqn → id. |
