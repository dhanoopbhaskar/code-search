---
type: Function
title: "profile_model_available"
description: "Whether the active model profile is available locally."
resource: code_search/engine/embeddings.py#profile_model_available
tags: [embeddings, function]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: code_search/engine/embeddings.py
    id: source-code
---

# Overview

Returns whether the active embedding model profile can be used locally,
without triggering a download. The `default` profile always returns `True`
(its model is bundled as the fallback); the opt-in `fast` profile returns
`False` until it is explicitly shipped and a measured local candidate
exists. Defined in
[`engine.embeddings`](../modules/engine/embeddings.md).

# Signature

`def profile_model_available(settings: Settings) -> bool`

# Parameters

| Name | Type | Description |
|---|---|---|
| `settings` | `Settings` | Active settings carrying `model_profile` and paths. |

# Returns

`True` when the profile's model can be used locally.
