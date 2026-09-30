---
type: Function
title: "verify_air_gap"
description: "Verify that air-gap enforcement is active."
resource: src/engine/redactor.py#verify_air_gap
tags: [security, compliance, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/redactor.py
    id: source-code
---

# Overview

Verifies that [`air_gap_enforcement`](air_gap_enforcement.md)
is currently active by running one loopback connection attempt
(`127.0.0.1:1`) inside the enforcement context and suppressing the expected
`RuntimeError`; a `True` result confirms the blocking socket patch is
installed. Defined in
[`engine.redactor`](../modules/engine/redactor.md).

# Signature

`def verify_air_gap() -> bool`

# Returns

`True` when the enforcement context activates without error, `False` otherwise.
