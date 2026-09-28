---
type: Function
title: "allow_downloads"
description: "Context manager temporarily allowing outbound socket connections."
resource: src/engine/redactor.py#allow_downloads
tags: [security, compliance, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/redactor.py
    id: source-code
---

# Overview

Context manager that temporarily lifts air-gap enforcement to allow
outbound socket connections, used for model downloads. Defined in
[`engine.redactor`](/modules/engine/redactor.md); used by
[`cmd_download_models`](/functions/cmd_download_models.md).

# Signature

`def allow_downloads() -> Generator[None, Any, None]`

# Returns

A context manager restoring air-gap enforcement on exit.
