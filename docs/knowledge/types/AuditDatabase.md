---
type: Class
title: "AuditDatabase"
description: "Append-only SQLite database for the query audit trail; enforces immutability via SQLite triggers."
resource: src/engine/audit.py#AuditDatabase
tags: [audit, compliance, storage]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/audit.py
    id: source-code
---

# Overview

Append-only SQLite database recording every search, symbol-lookup,
call-graph, `find_related`, and implementation-lookup query.
`UPDATE`/`DELETE` are blocked at the SQLite trigger level for compliance.
Defined in [`engine.audit`](/modules/engine/audit.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self, db_path: Path) -> None` | Initialize the audit database at *db_path*, creating triggers on first run. |
| `log_query(self, query_type: str, query_text: str, result_count: int, duration_ms: float, redaction_count: int = 0) -> None` | Append an audit record for a single query. |
| `get_recent(self, limit: int = 100) -> list[dict[str, Any]]` | Return the most recent audit records. |
