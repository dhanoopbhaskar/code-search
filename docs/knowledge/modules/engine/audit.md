---
type: Module
title: "engine.audit"
description: "Append-only audit log for query tracking and compliance, with SQLite trigger-enforced immutability."
resource: src/engine/audit.py
tags: [engine, audit, compliance]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/audit.py
    id: source-code
---

# Overview

Append-only audit log for query tracking and compliance. Records every
search, symbol lookup, call-graph, `find_related`, and
implementation-lookup query with timestamps, result counts, duration, and
redaction counts. `UPDATE` and `DELETE` operations are blocked at the
SQLite trigger level.

# Key Classes

- [`AuditDatabase`](/types/AuditDatabase.md) — append-only SQLite database for the query audit trail; enforces immutability via SQLite triggers.
