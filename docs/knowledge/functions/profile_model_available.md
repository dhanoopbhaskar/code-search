---
type: Function
title: "profile_model_available"
description: "Whether the active model profile is available locally."
resource: src/engine/embeddings.py#profile_model_available
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: src/engine/embeddings.py
    id: source-code
---

# Overview

Returns whether the active embedding model profile (`potion-code-16m-32d`)
is available locally under the models directory, without triggering a
download. Defined in
[`engine.embeddings`](/modules/engine/embeddings.md).

# Signature

`def profile_model_available(models_dir: Path) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `models_dir` | `Path` | Directory where models are stored. |

# Returns

`True` if the model files are present locally.
