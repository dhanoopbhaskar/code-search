---
type: Class
title: "Redactor"
description: "Regex-based secret redactor that applies patterns to text and tracks redaction counts."
resource: src/engine/redactor.py#Redactor
tags: [security, redaction, compliance]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/redactor.py
    id: source-code
---

# Overview

Regex-based secret redactor applying `SECRET_PATTERNS` to text and
replacing matches with `[REDACTED]`, tracking cumulative redaction
counts. Defined in
[`engine.redactor`](/modules/engine/redactor.md); consumed by
[`MetricsCollector`](/types/MetricsCollector.md) and
[`AuditDatabase`](/types/AuditDatabase.md).

# Methods

| Method | Description |
|---|---|
| `__init__(self) -> None` | Initialize with zeroed redaction counters. |
| `redact(self, text: str) -> tuple[str, int]` | Apply all secret patterns to *text*; return `(redacted_text, count)`. |
| `total_redactions() -> int` | Return the cumulative count of redactions performed. |
