---
type: Class
title: "Redactor"
description: "Regex-based secret redactor that applies patterns to text and returns redaction counts."
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
replacing matches with `[REDACTED]` and returning per-call redaction
counts. Defined in
[`engine.redactor`](../modules/engine/redactor.md); consumed by the CLI,
MCP server, and daemon query paths.

# Methods

| Method | Description |
|---|---|
| `__init__(patterns: list[tuple[str, str, re.Pattern[str]]] \| None = None) -> None` | Create a redactor using the given patterns or the built-in defaults. |
| `redact(text: str) -> tuple[str, int]` | Redact secrets in *text*, returning `(redacted_text, count)`. |
| `redact_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]` | Redact the `"content"` (and, when present, `"line_content"`) fields of every result dict in place. |
