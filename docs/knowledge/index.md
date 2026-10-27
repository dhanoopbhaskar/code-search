---
okf_version: "0.2"
---

# code-search Knowledge Base

An Open Knowledge Format (OKF v0.2) bundle documenting **code-search**: an
AI code context engine for air-gapped, CPU-only enterprise environments.
It combines Tree-sitter AST structural graphing with static Model2Vec
embeddings and BM25 hybrid search, and exposes the resulting SQLite code graph
through bounded discovery surfaces, a read-only Cypher subset, and a
single-question router — all reachable from a CLI, an MCP stdio server, and an
optional warm daemon.

All concepts in this bundle were machine-generated from the source tree at
`code_search/` and are `status: draft`, trust tier **unverified**, pending human
review.

# Sections

* [Modules](modules/index.md) - Package and file-level documentation, mirroring the `code_search/` tree.
* [Types](types/index.md) - Classes and dataclasses defined across the codebase.
* [Functions](functions/index.md) - Public top-level functions.
* [Architecture](architecture/index.md) - System overview and design patterns.
* [Config](config/index.md) - Environment variables and build/tooling configuration.
