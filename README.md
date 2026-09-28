# code-search

An AI code context engine for air-gapped, CPU-only enterprise environments. Combines Tree-sitter AST structural graphing with static Model2Vec embeddings + BM25 hybrid search, exposed via CLI and MCP stdio server.

## Features

- **Natural language code search** — hybrid BM25 + vector search with RRF fusion
- **Symbol definition lookup** — resolve any symbol by fully qualified name (FQN)
- **Call graph traversal** — navigate upstream callers and downstream callees
- **Session-aware ranking** — recently modified files rank higher in results
- **MCP protocol server** — expose search, symbol, and graph tools to MCP-compatible AI assistants
- **Enterprise compliance** — zero outbound network calls, secret redaction, append-only audit logging

## Requirements

- Python 3.11+
- 4+ cores, 8GB+ RAM
- Linux (CPU-only, no GPU required)
- No network access required (air-gap compliant)

## Installation

### Development (editable)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### From a pre-built bundle (no network required)

```bash
tar xzf code-search-0.1.0-bundle.tar.gz
cd bundle
python install-from-bundle.py
```

Installs into `./.venv` with the bundled embedding model included (fully offline, no download prompt). See [Install in another repo](#install-in-another-repo) for the full flag reference.

### From wheel directly

```bash
pip install code-search-*.whl
```

## Quick Start

### Index a codebase

```bash
code-search index --path /path/to/project
```

### Search with natural language

```bash
code-search search "how is JWT validation implemented" --limit 5
code-search search "database connection pool settings" --content config   # config chunks only
code-search search "how to run the dev server" --content docs             # docs chunks only
code-search search "public Comment save" --mode exhaustive --matching literal --json
```

`--content {code,config,docs,all,code_focused}` scopes a search to one content
axis. Omitting `--content` means **no scope preference**: the effective default
is **code-focused** — prose/docs chunks (markdown/`.rst`/`.txt`) are excluded
from ranked results, so docs never pollute code answers, while configuration is
included. On top of that default, **intent inference** runs on the ranked path:
a documentation-shaped query (for example "readme documentation", "how to
deploy") whose default search finds nothing is automatically re-run with content
scope `all`, and a non-empty default result is returned unchanged with a strong
suggestion instead of a silent empty answer. A configuration-shaped query never
changes the effective scope (configuration is already included), and its
guidance is **accurate**: a scope that includes configuration never claims
configuration is excluded. An explicit `--content` value always overrides
inference.

The applied scope is echoed as `content` and in the additive scope object
(`{effective, origin, intent, suggested, signal, override}`), where `origin` is
`explicit`, `inferred`, or `default`, `signal` is the surface-neutral message
when one is due, and `override` names the scope (`all` for documentation intent,
`config` for configuration intent) that forces the content type in. Inference
can be disabled with `CODE_SEARCH_INTENT_SCOPE_ENABLED=false`, which restores
single-pass, pre-inference behaviour.

`--content code` restricts the pool to source code only, which improves
precision on code questions but does not repair abstract-paraphrase failures
— a query that shares no tokens with the answer still misses it regardless of
scope. It also **excludes config/resource content**; when a code-scoped query
shows config-shaped intent (e.g. "where is the mysql url"), the response
envelope carries an accurate direction to include it (`--content config` or
`--content all`).

`--matching {literal,all_tokens,any_token}` selects the exhaustive matching
semantics per request (default `all_tokens`): `literal` treats the whole
query as one verbatim substring, `any_token` keeps OR semantics. Every
exhaustive result set labels its `matching_semantics` so a count is never
presented as an exact-phrase count.

Every ranked response also reports `query_time_ms`, the measured
`model_status` (`warm`/`cold`/`disabled`), the additive `ranked_path`
(`hybrid`/`lexical_reduced`/`lexical_degraded`) and `warmup_state`, and — when
vector signals are off — a visible `degraded_reason`
(`warming`/`model_disabled`/`model_unavailable`) instead of a silent false. A
ranked query that arrives while the model is still warming is answered
immediately from the labelled `lexical_reduced` cold path rather than blocking
on the load; once warm it is the unchanged hybrid path.

Docs search (`--content docs`) is rank-only: prose results carry no per-file
relevance or confidence signal. This is accepted while the docs corpus stays
small (see [docs/docs_search.md](docs/docs_search.md)); the revisit trigger is
the corpus exceeding 1,000 prose chunks or ~1 MB of indexed docs text. A
long-running server also detects an out-of-band index rebuild and returns a
visible "index changed — restart required" envelope instead of silent
empty/stale results.

### Look up a symbol

```bash
code-search symbol "myproject.auth.jwt.validate_token"
```

### Traverse the call graph

```bash
code-search graph "myproject.auth.jwt.validate_token" --depth 2
code-search graph "myproject.auth.jwt.validate_token" --transitive --depth 2
```

Each caller/callee appears once at its minimum depth. Direct-only is the
default; add `--transitive` to expand to `--depth` (bounded by the configured
graph depth). Pass `--direction implements` to return the static types that
implement an interface method instead:

```bash
code-search graph "myproject.auth.ArticleRepository.findBySlug" --direction implements
```

### Find interface implementations

```bash
code-search implementations "myproject.auth.ArticleRepository.findBySlug"
code-search implementations "myproject.auth.ArticleRepository.findBySlug" --json
```

Resolves an interface method (or type) reference and returns every static
implementing type with a navigable location, labelling each as `direct` or
`indirect` and reporting an inherited declaration against the class that
actually declares it. When a repository-style interface has no static
implementer the command prints the honest `no_static_implementation`
explanation (a runtime-generated implementation may exist) rather than
inventing a proxy.

### Repeatable queries with the query daemon

Every CLI invocation is a fresh process, and loading the vector model takes
time. The CLI handles this transparently: with no daemon running, `search`
starts the local unix-socket query daemon in the background (fire-and-forget)
and answers the first query from the reduced cold path while the single resident
load warms; subsequent invocations are served warm and fast. You can also manage
the daemon explicitly (air-gapped, socket under `.context/`):

```bash
code-search daemon start
code-search search "how is JWT validation implemented" --limit 5   # warm, fast
code-search search "pagination"                                     # warm, fast
code-search daemon status                                            # running (... warm)
code-search daemon stop
```

When a warm daemon is running the CLI forwards to it; otherwise it answers from
the in-process reduced path, which stays correct and labelled. Batch scripts
that want to skip vector-model warm-up entirely can use the `--no-model` fast
path (lexical-only fusion, no model load):

```bash
code-search search "pagination" --no-model
```

### View operational metrics

```bash
code-search metrics
code-search metrics --format json
code-search metrics --format prometheus
```

### View audit logs

Every search, symbol lookup, call graph, find_related, and implementation-lookup query is recorded in an append-only SQLite audit log at `.context/audit.db` (rows cannot be updated or deleted). View the most recent entries:

```bash
sqlite3 .context/audit.db \
  "SELECT id, timestamp, query_type, query_summary, result_count, duration_ms, redacted_count \
   FROM audit_log_entries ORDER BY id DESC LIMIT 20;"
```

Filter by query type (`search`, `get_symbol_definition`, `get_call_neighbors`, `find_related`, `get_implementations`):

```bash
sqlite3 .context/audit.db \
  "SELECT id, timestamp, query_summary, result_count, duration_ms \
   FROM audit_log_entries WHERE query_type = 'search' ORDER BY id DESC LIMIT 20;"
```

`code-search metrics` also reports the total entry count.

### Start MCP server

```bash
code-search serve
```

Then connect any MCP-compatible client to send JSON-RPC requests.

## Development

### Running tests

```bash
# Run all tests
pytest tests/

# Unit tests
pytest tests/unit/ -v

# Integration tests (requires an indexed codebase)
pytest tests/integration/ -v

# Contract tests
pytest tests/contract/ -v
```

### Real-world Java codebase tests

End-to-end tests run against a real Spring Boot application (`test-repo/` submodule). These exercise search, symbol lookup, graph traversal, resource file indexing, redaction, and JSON output formats against a production-style Java project.

```bash
# Initialize the submodule first
git submodule update --init

# Run (automatically indexes on first run)
pytest tests/test_repo/ -v

# Skip re-indexing if the cached index exists
pytest tests/test_repo/ -v --keep-index

# Force a full re-index
pytest tests/test_repo/ -v --keep-index --force-index
```

### Acceptance tests

The acceptance suite exercises every CLI command and MCP tool against a real (or sample) codebase end-to-end. It validates the full pipeline: index → search → symbol lookup → graph traversal → metrics → audit log → session tracking → redaction → air-gap.

```bash
# Against the built-in sample repo (fast, CI/smoke testing)
pytest tests/acceptance/ -v

# Against any real repo
pytest tests/acceptance/ -v --repo-path /path/to/repo

# Skip slow reindex tests on large repos
pytest tests/acceptance/ -v --repo-path . -m "not slow"

# Keep the cached index between runs (skips re-index)
pytest tests/acceptance/ -v --repo-path . --keep-index

# Convenience script
./tests/acceptance/run_acceptance.sh --repo-path .
```

The default sample repo contains Python, JavaScript, Java, XML, SQL, and properties files with embedded secrets for redaction verification. Set `--repo-path` to validate against any real project.

### Lint & type check

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/

# Format
ruff format src/ tests/

# Run all quality checks
make check
```

## Project Structure

```
.
├── Makefile           # Build, bundle, install, clean
├── pyproject.toml     # Package metadata & build config
├── scripts/
│   ├── bundle.py              # Cross-platform bundle builder (Windows/Mac/Linux)
│   └── install-from-bundle.py # Cross-platform bundle installer
├── src/
│   ├── engine/       # Core engine modules
│   ├── parser.py       # Tree-sitter AST parsing
│   ├── symbols.py      # Symbol extraction & FQN resolution
│   ├── graph.py        # SQLite graph DB (symbols, edges, chunks)
│   ├── search.py       # BM25 + vector hybrid search + RRF
│   ├── embeddings.py   # Model2Vec static embedding generation
│   ├── reranking.py    # Definition boost, noise penalties, session weight
│   ├── session.py      # Session activity tracking & weight decay
│   ├── redactor.py     # Secret/PII redaction pipeline
│   ├── audit.py        # Append-only audit log
│   ├── indexer.py      # Full/incremental indexing orchestration
│   ├── watcher.py      # File system watcher
│   └── metrics.py      # Operational metrics
├── cli/          # CLI entry point
│   └── main.py         # code-search CLI commands
├── mcp/          # MCP protocol server
│   └── server.py       # FastMCP stdio server with 4 tools
└── context/      # Context directory management
    └── __init__.py     # .context/ directory setup
```

## Distribution & Bundling

`code-search` can be packaged into a portable bundle for use in other repos without cloning the source.

### Build a bundle

```bash
# Build wheel + create tarball
make bundle

# Include offline dependency wheels (for air-gapped targets)
make bundle-deps
```

Output is `dist/code-search-<version>-bundle.tar.gz`.

### Bundle contents

```
bundle/
├── code_search-<version>-py3-none-any.whl   # installable wheel
├── install-from-bundle.py                    # one-command install script
├── models/                                   # (default) embedding model for offline vector search
│   └── potion-code-16m-32d/
├── deps/                                     # (optional) offline wheels
└── README.md
```

### Install in another repo

```bash
tar xzf code-search-0.1.0-bundle.tar.gz
cd bundle
python install-from-bundle.py
```

The script resolves the bundle directory from its own location, so you can run it from anywhere after extracting. By default it creates a `.venv` and installs the wheel plus the bundled embedding model into it.

| Flag | Effect |
|------|--------|
| `--venv PATH` | Venv location (default `.venv`, or the `VENV_DIR` env var) |
| `--global` | System install via pipx (falls back to `pip --user`) instead of a venv |
| `--force` | Reinstall even if the same version is already present |
| `--no-model` | Skip installing the bundled embedding model (breaks offline vector search). Installer flag only — unrelated to the `code-search search --no-model` fast path. |

Notes:
- The embedding model is bundled by default and installed to `<venv>/share/code-search/models/<name>`, so `Vector Model Avail: true` works air-gapped with zero network — no download prompt.
- If the bundle contains a `deps/` directory (from `make bundle-deps`), the installer uses `pip --no-index --find-links` for a fully offline install.
- `--global` falls back to `pip install --user` if the system Python refuses a global install (e.g. PEP 668 managed environments).
- After a venv install, activate it before running `code-search`: `source .venv/bin/activate` (Unix) or `.venv\Scripts\activate` (Windows).

### Automated builds

| Command | Description |
|---|---|
| `make build` | Build wheel + sdist |
| `make bundle` | Build + create portable tarball |
| `make bundle-deps` | Build + create tarball with offline deps |
| `make install` | Install wheel into active venv |
| `make download-deps` | Pre-download dependency wheels |
| `make clean` | Remove build artifacts |

### Air-gapped workflow

1. On a machine with network access: `make bundle-deps`
2. Copy the tarball to the air-gapped target
3. `tar xzf ... && cd bundle && python install-from-bundle.py`

The install script detects the `deps/` directory and uses `pip --no-index --find-links` for a fully offline install.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CODE_SEARCH_CONTEXT_DIR` | `.context` | Path to the context storage directory |
| `CODE_SEARCH_LOG_LEVEL` | `WARNING` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CODE_SEARCH_SESSION_TTL_HOURS` | `24` | Session entry TTL in hours |
| `CODE_SEARCH_RRF_K` | `60` | RRF ranking constant |
| `CODE_SEARCH_MAX_RESULTS` | `50` | Maximum results per search |

