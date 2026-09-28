---
type: Module
title: "engine.session"
description: "Session database tracking READ/WRITE navigation events with exponential decay for personalised reranking."
resource: src/engine/session.py
tags: [engine, session, personalization]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/session.py
    id: source-code
---

# Overview

Session database tracking READ/WRITE events for personalised ranking.
Each event gets a base weight (`WRITE=1.0`, `READ=0.7`) that decays
exponentially over time. Recently accessed files receive a boost during
reranking via `get_weights_for_files()`.

# Key Classes

- [`SessionDatabase`](/types/SessionDatabase.md) — tracks code navigation events to enable session-based personalised reranking with exponential decay.
