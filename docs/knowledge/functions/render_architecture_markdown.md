---
type: Function
title: "render_architecture_markdown"
description: "Render an ArchitectureReport as deterministic Markdown."
resource: code_search/engine/graph_query.py#render_architecture_markdown
tags: [graph, function, rendering]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-19T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Produces the `# Graph Architecture Report` document with four sections: god
nodes (table of symbol, kind, degree, file), communities (up to eight members
each), import cycles, and suggested questions. Output is deterministic for a
given report and ends with a trailing newline. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def render_architecture_markdown(report: ArchitectureReport) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `report` | [`ArchitectureReport`](../types/ArchitectureReport.md) | The report to render. |

# Returns

The Markdown text.
