---
type: Module
title: "engine.graph_passes"
description: "Deterministic post-index enrichment passes that store canonical FQNs, TESTS and interface-dispatch edges, entry-point classification, importance, and symbol degrees."
resource: code_search/engine/graph_passes.py
tags: [engine, graph, enrichment, indexing]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-27T14:20:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_passes.py
    id: source-code
---

# Overview

Extraction stores what is written in the code; these passes store what has to be
derived from the whole graph so an agent query does not have to guess it.
Each pass runs inside the same write transaction as the index and is safe to
re-run on a full or incremental build.

| Pass | Stored fact |
|---|---|
| [`backfill_canonical_fqns`](../../functions/backfill_canonical_fqns.md) | `canonical_fqn` = `<repo-relative path>::<declaration>` on every symbol |
| [`backfill_test_flags`](../../functions/backfill_test_flags.md) | `symbols.is_test` from the shared path classifier |
| [`derive_tests_edges`](../../functions/derive_tests_edges.md) | `TESTS` edges from test-symbol references to production code |
| [`derive_interface_dispatch_edges`](../../functions/derive_interface_dispatch_edges.md) | resolved `CALLS` edges from interface call sites to implementations |
| [`classify_entry_points`](../../functions/classify_entry_points.md) | `is_entry_point` and `entry_point_reason` |
| [`compute_importance`](../../functions/compute_importance.md) | adapted weighted-degree importance |
| [`rebuild_symbol_degrees`](../../functions/rebuild_symbol_degrees.md) | `symbol_degrees` rows per symbol and edge type |

[`rebuild_derived_graph_data`](../../functions/rebuild_derived_graph_data.md)
runs the whole sequence and returns a deterministic summary of how many rows
each pass touched.

# Rules Worth Knowing

- `canonical_fqn` is **additive**: `fqn` keeps its absolute-path spelling so
  existing queries keep working, while the canonical form stays stable across
  worktrees and usable for snapshot comparison.
- A `TESTS` edge is derived rather than extracted: every resolved edge
  (`CALLS`, `USAGE`, `CALL_REFERENCE`, `REFERENCES`, `IMPLEMENTS`, `INHERITS`)
  whose source lives in a test file and whose target does not becomes a direct
  test-to-production edge. Prior derived rows are replaced, so an incremental
  run cannot leave stale relationships behind.
- Interface-dispatch edges close the gap where `provider.handle()` resolves to
  the interface method and a path or impact walk never reaches the class that
  actually handles the call. Existing direct edges win (`INSERT OR IGNORE`).
- Entry-point reasons are evaluated in order and the first match wins: test
  symbol, `main`, constructor, override/implementation, exported top-level
  symbol, annotated framework handler, then a configured name/glob
  (`CODE_SEARCH_ENTRY_POINTS`). Only top-level public declarations count as
  exported API, so ordinary public methods are not all classified as entry
  points.
- Importance is documented and deterministic:

      importance = sqrt(incoming CALLS + USAGE)
                 * 0.1 for private symbols
                 * 0.1 when the name is defined in >= 5 distinct files
                 * 10  for a descriptive name of at least 8 characters
                 * 0.1 for test scaffolding

  Scores are rounded to six decimals so the same index always produces the same
  values.
