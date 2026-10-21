---
type: Function
title: "render_impact_text"
description: "Render an ImpactAnswer as text with production and test buckets."
resource: code_search/engine/graph_query.py#render_impact_text
tags: [graph, output, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-10-21T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/graph_query.py
    id: source-code
---

# Overview

Renders an [`ImpactAnswer`](../types/ImpactAnswer.md) as a summary line plus
two path buckets: `production` and `tests`, classified per path. Each file
lists its impacted symbols via
[`display_symbol`](display_symbol.md); impacted-symbol paths are printed
through [`relative_display`](relative_display.md) so output is root-relative
while already-relative impacted filenames stay as stored. Defined in
[`engine.graph_query`](../modules/engine/graph_query.md).

# Signature

`def render_impact_text(answer: ImpactAnswer, *, root: str | Path | None = None) -> str`

# Parameters

| Name | Type | Description |
|---|---|---|
| `answer` | `ImpactAnswer` | The impact envelope returned by `GraphQueryService.impact`. |
| `root` | `str \| Path \| None` | Indexed repository root used to relativise paths; omitted means stored spellings. |

# Returns

The rendered multi-line text report.
