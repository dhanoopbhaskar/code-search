---
type: Function
title: "derive_tests_edges"
description: "Rebuild `TESTS` edges from test-symbol references to production code."
resource: code_search/engine/graph_passes.py#derive_tests_edges
tags: [engine, function, graph_passes]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Rebuild `TESTS` edges from test-symbol references to production code.

Defined in [`engine.graph_passes`](../modules/engine/graph_passes.md).

# Signature

`def derive_tests_edges(conn: Any) -> int`

# Notes

A `TESTS` edge is derived, not independently extracted: every resolved
`CALLS`/`USAGE`/`CALL_REFERENCE`/`REFERENCES`/`IMPLEMENTS`/
`INHERITS` edge whose source symbol lives in a test file and whose target
does not becomes a direct test-to-production edge. Existing derived rows
are replaced so an incremental run cannot leave stale test relationships.
