---
type: Function
title: "air_gap_enforcement"
description: "Context manager blocking all outbound socket connections."
resource: src/engine/redactor.py#air_gap_enforcement
tags: [security, compliance, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/redactor.py
    id: source-code
---

# Overview

Context manager that monkey-patches `socket` to block all outbound
connections for the duration of the block, enforcing air-gap compliance.
Defined in [`engine.redactor`](/modules/engine/redactor.md).

# Signature

`def air_gap_enforcement() -> Generator[None, Any, None]`

# Returns

A context manager restoring normal socket behavior on exit.
