---
type: Overview
title: "Build System"
description: "pyproject.toml dependencies, Makefile targets, and packaging scripts."
resource: pyproject.toml
tags: [config, build, packaging]
generated: { by: code-documenter/skill-v1.0, at: 2026-09-28T00:00:00Z }
status: draft
sources:
  - resource: pyproject.toml
    id: source-code
  - resource: Makefile
    id: source-code
---

# Overview

`code-search` is packaged as a standard setuptools project
(`pyproject.toml`), targeting Python 3.11+, with a `Makefile` and
`scripts/` wrapping build, quality-check, and offline-bundle workflows
for air-gapped deployment.

# Dependencies

Core (`[project.dependencies]`): `tree-sitter` plus per-language grammars
(`tree-sitter-python`, `-java`, `-javascript`, `-typescript`, `-c-sharp`,
`-cpp`, `-bash`, `-yaml`), `model2vec` (embeddings), `rank-bm25`,
`fastmcp` (MCP server), `watchdog` (file watching).

Optional dependency groups (`[project.optional-dependencies]`):

- `dev` — `pytest`, `pytest-asyncio`, `pytest-benchmark`, `hypothesis`,
  `ruff`, `mypy`.
- `lang` — additional tree-sitter grammars (Go, Rust, Ruby, Swift,
  Kotlin, PHP, TOML, C++, C#).
- `prod` — `prometheus-client`, `presidio-analyzer` (production metrics
  and PII detection).

# Entry Point

`code-search = "src.cli.main:main"` — installs the `code-search` console
script backed by [`main`](/functions/main.md).

# Tooling Configuration

- **Ruff** (`[tool.ruff]`): `target-version = py311`, `line-length = 100`;
  lint rule sets `E, F, I, N, W, UP, B, SIM, ARG, PTH, PD, RUF`; test
  directories get relaxed per-file ignores (e.g. `S101` assert-use,
  `ARG00x` unused args in fixtures).
- **Mypy** (`[tool.mypy]`): `python_version = 3.12`, `strict = true`;
  third-party packages without stubs (tree-sitter grammars, `model2vec`,
  `rank_bm25`, `fastmcp`, `watchdog`, `presidio_analyzer`, `numpy`) are
  exempted via `ignore_missing_imports`.
- **Pytest** (`[tool.pytest.ini_options]`): `testpaths = ["tests"]`,
  `asyncio_mode = "auto"`; custom markers `slow`, `benchmark`, `contract`,
  `integration`, `acceptance`, `test_repo` gate optional test suites.

# Makefile Targets

| Target | Purpose |
|---|---|
| `make build` | Build wheel + sdist via `python -m build`. |
| `make install` | Install the built wheel into the active environment. |
| `make editable` | `pip install -e ".[dev]"` for local development. |
| `make bundle` | Build + create a portable tarball (`scripts/bundle.py`). |
| `make bundle-deps` | Same as `bundle`, including offline dependency wheels. |
| `make download-deps` | Download dependency wheels into `wheelhouse/` for offline install. |
| `make check` / `lint` / `format` / `typecheck` / `test` | Run quality gates via `scripts/check.sh` (with the matching flag). |
| `make clean` | Remove build artifacts (`build/`, `*.egg-info`, `__pycache__`). |
| `make distclean` | `clean` plus `dist/`, `wheelhouse/`, tox/nox and coverage caches. |

# Scripts

- `scripts/check.sh` — runs lint/format/typecheck/test, invoked by the
  Makefile quality-gate targets.
- `scripts/bundle.py` — builds the portable/offline install tarball.
- `scripts/install-from-bundle.py` / `.sh` — installs `code-search` from
  a pre-built bundle on an air-gapped machine.
- `scripts/benchmark.sh` — runs the benchmark test suite
  (`tests/benchmarks/`).
- `scripts/check_comment_refs.py` — validates that in-code comment
  references stay consistent (repo-specific lint helper).

# See Also

- [Environment Configuration](/config/environment.md)
