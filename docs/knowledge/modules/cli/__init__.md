---
type: Module
title: "src.cli"
description: "Command-line interface package for code-search."
resource: src/cli/__init__.py
tags: [cli, package]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/cli/__init__.py
    id: source-code
---

# Overview

Command-line interface for code-search. Dispatches the `index`, `search`,
`symbol`, `graph`, `metrics`, `serve`, `list-languages`, `download-models`,
and `daemon` subcommands via the [`main`](/modules/cli/main.md) module.
