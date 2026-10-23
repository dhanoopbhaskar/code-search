# code-search

An AI code context engine for air-gapped, CPU-only enterprise environments. Combines Tree-sitter AST structural graphing with static Model2Vec embeddings + BM25 hybrid search, exposed via CLI and MCP stdio server.

## Features

- **Natural language code search** — hybrid BM25 + vector search with RRF fusion
- **Symbol definition lookup** — resolve any symbol by fully qualified name (FQN)
- **Call graph traversal** — navigate upstream callers and downstream callees
- **Session-aware ranking** — recently modified files rank higher in results
- **MCP protocol server** — expose the full search, symbol, graph, and impact toolset to MCP-compatible AI assistants
- **Enterprise compliance** — no outbound network calls during search or serving, secret redaction, append-only audit logging

## Requirements

- Python 3.11+
- 4+ cores, 8GB+ RAM
- Linux (CPU-only, no GPU required); bundle build/install tooling also runs on Windows and macOS
- No network access required for search or serving when the embedding model is available locally (air-gap compliant)

## Installation

### Development (editable)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### From a pre-built bundle

```bash
tar xzf code-search-0.1.0-bundle.tar.gz
cd bundle
python install-from-bundle.py
```

Installs into `./.venv` with the bundled embedding model included, so vector search works without a model download prompt. A default `make bundle` does not include dependency wheels; a fully offline install requires a bundle built with `make bundle-deps` and local `pip`/`wheel` availability. See [Install in another repo](#install-in-another-repo) for the full flag reference.

### From wheel directly

```bash
pip install code-search-*.whl
```

### From git (pipx)

Installs the CLI into an isolated environment on your `PATH`:

```bash
pipx install --force "git+https://github.com/dhanoopbhaskar/code-search"
```

## Quick Start

### When to use code-search vs grep

Use `code-search` when you do not know the exact identifier yet, when you need
ranked definitions rather than every textual occurrence, or when the question is
structural ("who calls this", "what implements this interface"). Use `grep`/`rg`
when you already know the literal string, need an exact mechanical inventory, or
want line-oriented enumeration. Inside code-search, `--mode exhaustive --regex`
covers that exact-enumeration case without leaving the tool.

### Recommended warm invocation

```bash
code-search start                                  # once per machine/session
code-search search "<query>" --json --paths-only   # discovery
code-search search "<regex>" --mode exhaustive --regex  # enumeration
code-search symbol <Fqn>                           # definitions
code-search graph <Fqn> --explain-unresolved       # structural answers
```

### Index a codebase

```bash
code-search index --path /path/to/project
```

Indexing honours the repository's `.gitignore` files (plus built-in build and
tool directories such as `target/`, `graphify-out/`, and `.opencode/`), so
generated artifacts do not pollute results. Explicit `--exclude` patterns are
additive. To index ignored paths anyway, set
`CODE_SEARCH_RESPECT_GITIGNORE=false`.

### Search with natural language

```bash
code-search search "how is JWT validation implemented" --limit 5
code-search search "database connection pool settings" --content config   # config chunks only
code-search search "how to run the dev server" --content docs             # docs chunks only
code-search search "public Comment save" --mode exhaustive --matching literal --json
```

`--content {code,config,docs,all,code_focused}` scopes a search to one content
axis. Omitting `--content` means **no scope preference** and lets **query-intent
inference** choose on the ranked path. A fuzzy code-shaped query (a short
word such as "login", a snake_case identifier, code vocabulary such as
"function" or "controller", or a code construct noun such as "handler" or
"repository") searches `code` only, so configuration and build
files cannot outrank source on shared vocabulary. Exact symbol-shaped queries
(`AuthService`, `ArticleService.save`) keep the broader default because their
exact-match boost already outranks configuration. A documentation-shaped query
(for example "readme documentation", "how to deploy") widens the scope to
`all` immediately and lifts prose chunks, so a code result that merely mentions
the words does not automatically outrank the prose answer. Other queries use
`code_focused` (code + config, **docs excluded**); a configuration-shaped query
keeps configuration reachable and its guidance is **accurate** — a scope that
includes configuration never claims configuration is excluded. An explicit
`--content` value always overrides inference.

Test files are excluded from ranked search by default; add `--include-tests`
(or `include_test_files: true` on MCP) when the test itself is the answer.
Ranked envelopes always split the match count into `production_matches` and
`test_matches`, so hidden tests never silently change the total.
Machine-readable search output is compact by default: identifiers, locations,
signatures, and a short content snippet, with `--no-compact` returning the full
blocks and `score_sources`. Each ranked envelope carries `token_savings`
(returned tokens vs reading the whole files) so an agent can see the budget it
saved.

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

`--mode {ranked,exhaustive,enumerate}` selects the search mode: `ranked`
(default) uses hybrid ranking, `exhaustive` scans line by line for an exact
match set, and `enumerate` lists the definitions of a named symbol kind (for
example "list all controllers").

`--matching {literal,all_tokens,any_token}` selects the exhaustive matching
semantics per request (default `all_tokens`): `literal` treats the whole
query as one verbatim substring, `any_token` keeps OR semantics. Every
exhaustive result set labels its `matching_semantics` so a count is never
presented as an exact-phrase count.

`--regex` compiles the query as a regular expression and scans line by line;
it requires `--mode exhaustive` and labels the result set
`matching_semantics: "regex"`. An invalid pattern is reported as an
`invalid_regex` explanation rather than silently returning nothing.

For repeated CLI use, run `code-search daemon start` once so a resident
process owns the model load. `--no-startup-check` skips the transparent
daemon auto-start for a single invocation and serves it locally.

Every ranked response also reports `query_time_ms`, a structured
`model_status`, the additive `ranked_path`
(`hybrid`/`lexical_reduced`/`lexical_degraded`) and `warmup_state`, and — when
vector signals are off — a visible `degraded_reason`
(`warming`/`model_disabled`/`model_unavailable`) instead of a silent false.
On healthy paths `model_status` is an object whose `state` is
`warm`/`cold`/`initializing` (a cold-start request reports `initializing`);
when the model is disabled or unavailable it is the string `disabled`. The
engine serves a cold request from the labelled `lexical_reduced` path without
blocking on the model load. The daemon and MCP server wait up to
`CODE_SEARCH_WARMUP_WAIT_S` (default 5 seconds) for the shared model, then fall
back to the same labelled cold path if warmup does not finish in time; once
warm, the path is the unchanged hybrid ranking.

Docs search (`--content docs`) scopes the ranked pool to prose chunks. Prose
results use the same hybrid ranking path as code and carry the same per-result
`confidence`, `confidence_band`, and `borderline` fields. A long-running server
also detects an out-of-band index rebuild and returns a visible "index changed
— restart required" envelope instead of silent empty/stale results.

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

### Query the graph (multi-hop)

`code-search query` seeds a bounded graph traversal from the hybrid search
ranker and returns a compact neighbourhood with a confidence label on every
edge (`EXTRACTED`, `INFERRED`, `AMBIGUOUS`, or `UNRESOLVED`). Seeds are taken
from the same reranked hits the search surface returns, and each seed reports
why it was chosen (hybrid rank/score, term coverage, or an explicit reference).

```bash
code-search query "how does favoriting an article flow from controller to repository"
code-search query "who calls ArticleRepository.save" --depth 3 --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--depth N` | `2` | Traversal depth (max: 4) |
| `--max-nodes N` | `120` | Maximum graph nodes (max: 200) |
| `--edge-types LIST` | `CALLS,INHERITS` | Comma-separated edge types (`IMPORTS` and `REFERENCES` are opt-in) |
| `--token-budget N` | `1500` | Soft output budget; the answer is trimmed deterministically |
| `--json` | — | Structured JSON output |

### Shortest path

```bash
code-search path "ArticleController.favoriteArticle" "ArticleRepository.save"
code-search path "ArticleController.favoriteArticle" "ArticleRepository.save" --undirected
```

| Flag | Default | Description |
|------|---------|-------------|
| `--undirected` | off | Traverse edges in both directions |
| `--max-hops N` | `6` | Maximum path length (max: 6) |
| `--edge-types LIST` | `CALLS,INHERITS` | Comma-separated edge types (`CALLS`, `INHERITS`, `REFERENCES`, `IMPORTS`) |
| `--json` | — | Structured JSON output |

### Explain a symbol

```bash
code-search explain "ArticleMutation.favoriteArticle"
code-search explain "ArticleRepository.save" --depth 2 --relations CALLS,INHERITS,IMPORTS
```

`explain` returns the symbol's location, signature, incoming and outgoing
relations, attached rationale comments (`NOTE:`/`WHY:`/`HACK:`/`TODO:`/
`FIXME:`/ADR), and offline documentation links. Doc links are computed at
index time only when `CODE_SEARCH_INDEX_DOC_LINKS=true` (default off); they
use the local embedding model plus deterministic symbol mentions and never make
a network call.

| Flag | Default | Description |
|------|---------|-------------|
| `--depth N` | `1` | Ego-graph depth (max: 4) |
| `--relations LIST` | `CALLS,INHERITS` | Comma-separated relations to include (`CALLS`, `INHERITS`, `REFERENCES`, `IMPORTS`) |
| `--json` | — | Structured JSON output |

### Impact analysis and architecture map

```bash
code-search affected --since HEAD~1
code-search affected src/main/java/io/spring/core/Article.java --depth 3
code-search map --output graph-report.md
```

| Command | Flags | Description |
|---|---|---|
| `affected` | `--since REF`, `--depth N`, `--json` | Reverse-traverse callers, subtypes, and importers of changed files |
| `map` | `--output FILE`, `--top N`, `--max-communities N`, `--json` | Write a deterministic architecture report (god nodes, communities, import cycles) |

### Repeatable queries with the query daemon

Every CLI invocation is a fresh process, and loading the vector model takes
time. The CLI handles this transparently: with no daemon running, `search`
starts the local unix-socket query daemon in the background and forwards to it
once it answers `ping`; the daemon waits briefly for the shared model load
(bounded by `CODE_SEARCH_WARMUP_WAIT_S`, default 5 seconds) so the first
forwarded query is usually hybrid. If the model does not warm in time, the
response is the labelled `lexical_reduced` cold path; if no daemon becomes
reachable, the invocation answers locally from that same cold path. Subsequent
invocations are served warm and fast. You can also manage the daemon explicitly
(air-gapped, socket under `.context/`):

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

Scores are ordered, not probabilities: weak matches are demoted, but a strong
match can exceed `1.0` rather than saturating at `1.00`. To audit why a result
ranked where it did, `--explain-ranking` adds `score_sources` and prints the
per-result multipliers and boosts:

```bash
code-search search "ArticleList loadArticles" --explain-ranking
```

### View operational metrics

```bash
code-search metrics
code-search metrics --format json
code-search metrics --format prometheus
```

### View audit logs

Every search, symbol lookup, call graph, find_related, implementation-lookup, graph-query, path, explain, impact, and map query is recorded in an append-only SQLite audit log at `.context/audit.db` (rows cannot be updated or deleted). View the most recent entries:

```bash
sqlite3 .context/audit.db \
  "SELECT id, timestamp, query_type, query_summary, result_count, duration_ms, redacted_count \
   FROM audit_log_entries ORDER BY id DESC LIMIT 20;"
```

Filter by query type (`search`, `get_symbol_definition`, `get_call_neighbors`, `find_related`, `get_implementations`, `query_graph`, `shortest_path`, `explain_symbol`, `get_impact`, `map`):

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

The acceptance suite exercises the primary CLI pipeline and a representative subset of MCP tools against a real (or sample) codebase end-to-end. It validates the full pipeline: index → search → symbol lookup → graph traversal → metrics → audit log → session tracking → redaction → air-gap.

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
ruff check code_search/ tests/

# Type check
mypy code_search/

# Format
ruff format code_search/ tests/

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
├── code_search/
│   ├── engine/       # Core engine modules (selected)
│   │   ├── parser.py       # Tree-sitter AST parsing
│   │   ├── symbols.py      # Symbol extraction & FQN resolution
│   │   ├── graph.py        # SQLite graph DB (symbols, edges, chunks)
│   │   ├── search.py       # BM25 + vector hybrid search + RRF
│   │   ├── embeddings.py   # Model2Vec static embedding generation
│   │   ├── reranking.py    # Definition boost, noise penalties, session weight
│   │   ├── session.py      # Session activity tracking & weight decay
│   │   ├── redactor.py     # Secret/PII redaction pipeline
│   │   ├── audit.py        # Append-only audit log
│   │   ├── indexer.py      # Full/incremental indexing orchestration
│   │   ├── watcher.py      # File system watcher
│   │   └── metrics.py      # Operational metrics
│   ├── cli/          # CLI entry point
│   │   └── main.py         # code-search CLI commands
│   ├── mcp/          # MCP protocol server
│   │   └── server.py       # FastMCP stdio server with 9 tools
│   └── context/      # Context directory management
│       └── __init__.py     # .context/ directory setup
```

The engine directory also contains supporting modules such as `config.py`,
`daemon.py`, `freshness.py`, `graph_query.py`, `implementations.py`,
`index_service.py`, `model_status.py`, `response_service.py`, and
`semantic_signals.py`.

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
- The embedding model is bundled by default and installed to `<venv>/share/code-search/models/<name>`, so `Vector Model Avail: true` works air-gapped with no model download prompt.
- If the bundle contains a `deps/` directory (from `make bundle-deps`), the installer uses `pip --no-index --find-links` for the wheel install. It still upgrades `pip` and `wheel` first, so a fully offline target must already provide or cache those packages.
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

The install script detects the `deps/` directory and uses `pip --no-index --find-links` for the wheel install. It still upgrades `pip` and `wheel` first, so the air-gapped target needs those packages available locally for a fully offline install.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CODE_SEARCH_CONTEXT_DIR` | `.context` | Path to the context storage directory |
| `CODE_SEARCH_LOG_LEVEL` | `WARNING` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CODE_SEARCH_SESSION_TTL_HOURS` | `24` | Session entry TTL in hours |
| `CODE_SEARCH_RRF_K` | `60` | RRF ranking constant |
| `CODE_SEARCH_MAX_RESULTS` | `50` | Maximum results per search |

