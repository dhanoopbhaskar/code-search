---
type: Class
title: "AuditDatabase"
description: "Append-only SQLite database for the query audit trail; enforces immutability via SQLite triggers."
resource: code_search/engine/audit.py#AuditDatabase
tags: [audit, compliance, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/audit.py
    id: source-code
---

# Overview

Append-only SQLite database recording every search, symbol-lookup,
call-graph, `find_related`, and implementation-lookup query.
`UPDATE`/`DELETE` are blocked at the SQLite trigger level for compliance.
Defined in [`engine.audit`](../modules/engine/audit.md).

# Methods

| Method | Description |
|---|---|
| `__init__(db_path: Path) -> None` | Create an audit database backed by the file at *db_path*. |
| `initialize() -> None` | Create the audit table, indexes, and append-only triggers. |
| `connect() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding the thread-local read connection. |
| `write_transaction() -> Generator[sqlite3.Connection, Any, None]` | Context manager yielding a dedicated connection for a write. |
| `write_entry(query_type: str, query_summary: str \| None = None, result_count: int = 0, duration_ms: int = 0, redacted_count: int = 0) -> int` | Append an audit entry, returning its row ID. |
| `get_entries(limit: int = 100, offset: int = 0, query_type: str \| None = None) -> list[sqlite3.Row]` | Query audit entries, most recent first, optionally filtered by type. |
| `count_entries(query_type: str \| None = None) -> int` | Count audit entries, optionally restricted to one *query_type*. |
| `close() -> None` | Close the thread-local connection if one has been opened. |
