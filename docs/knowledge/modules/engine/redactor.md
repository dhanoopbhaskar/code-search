---
type: Module
title: "engine.redactor"
description: "Secret redaction and air-gap enforcement (blocks outbound sockets) for enterprise compliance."
resource: src/engine/redactor.py
tags: [engine, security, compliance]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/redactor.py
    id: source-code
---

# Overview

Secret redaction and air-gap enforcement for enterprise compliance. Uses
regex-based pattern matching to detect and replace secrets (API keys,
tokens, passwords, etc.) with a `[REDACTED]` placeholder. Air-gap
enforcement monkey-patches `socket` to prevent outbound connections at
runtime.

# Key Constants

`SECRET_PATTERNS` — list of `(name, label, compiled_pattern)` tuples for
secret detection. `REDACTED_PLACEHOLDER = "[REDACTED]"`.

# Key Classes

- [`Redactor`](/types/Redactor.md) — regex-based secret redactor that applies patterns to text and tracks redaction counts.

# Key Functions

- [`allow_downloads`](/functions/allow_downloads.md) — context manager temporarily allowing outbound socket connections.
- [`air_gap_enforcement`](/functions/air_gap_enforcement.md) — context manager blocking all outbound socket connections.
- [`verify_air_gap`](/functions/verify_air_gap.md) — verify that air-gap enforcement is active.

# Internal Helpers

`_is_method_invocation_expression` excludes code-expression spans (e.g.
method calls) from being misclassified as secrets.
