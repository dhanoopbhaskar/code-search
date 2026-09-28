# code-search User Manual

## Table of Contents

- [Installation](#installation)
- [Setup](#setup)
  - [Download the embedding model](#1-download-the-embedding-model)
  - [Index your codebase](#2-index-your-codebase)
- [CLI Usage](#cli-usage)
  - [Search](#code-search-search)
  - [Symbol lookup](#code-search-symbol)
  - [Call graph traversal](#code-search-graph)
  - [Metrics](#code-search-metrics)
  - [List languages](#code-search-list-languages)
- [MCP Server](#mcp-server)
  - [Starting the server](#starting-the-server)
  - [MCP client configuration](#mcp-client-configuration)
  - [Available tools](#available-tools)
  - [Example JSON-RPC calls](#example-json-rpc-calls)
- [Configuration](#configuration)
- [Key points](#key-points)

---

## Installation

### From PyPI

```bash
pip install code-search
```

For extra language grammars (Go, Rust, Ruby, Swift, Kotlin, PHP, Shell, TOML):

```bash
pip install "code-search[lang]"
```

### From source (development)

```bash
pip install -e /path/to/code-search
```

### From a portable bundle (air-gapped targets)

```bash
# On a machine with network — build the bundle
./bundle.sh                            # basic bundle
./bundle.sh --deps                     # with offline dependency wheels

# Copy dist/code-search-*-bundle.tar.gz to the target, then:
tar xzf code-search-*-bundle.tar.gz
cd bundle
./install-from-bundle.sh
```

---

## Setup

### 1. Download the embedding model

```bash
code-search download-models
```

This fetches `potion-code-16m-32d` (CPU-only, 32-dim vector model from MinishLab).  
Without the model, search falls back to BM25-only (keyword matching).

### 2. Index your codebase

```bash
cd /path/to/your/repo
code-search index
```

Creates a `.context/` directory with all index data (SQLite databases + vector files).

**Useful flags:**

| Flag | Description |
|------|-------------|
| `--path PATH` | Path to codebase root (default: `.`) |
| `--force` | Force re-index (ignores lock) |
| `--incremental` | Only index changed files (checks SHA256) |
| `--watch` | Watch for changes after indexing |
| `--exclude PATTERNS` | Comma-separated exclusion patterns |
| `--no-include-tests` | Exclude test files |
| `--include-resources` / `-r` | Include resource files (XML, SQL, properties, etc.) (default) |
| `--exclude-resources` | Exclude resource files from indexing |
| `--resource-extensions EXTS` | Comma-separated override for resource file extensions |
| `--prune-stale` | Prune index rows for files no longer on disk / excluded, then exit |

---

## CLI Usage

### `code-search search`

Natural language hybrid search (BM25 + vector + RRF fusion).

```bash
code-search search "how is JWT validation implemented" --limit 5
code-search search "database connection pool" --language java --no-include-tests --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | `10` | Max results |
| `--language LANG` | — | Filter by language (python, java, typescript, etc.) |
| `--include-tests` / `--no-include-tests` | `true` | Include/exclude test files |
| `--content {code,config,docs,all,code_focused}` | `code_focused` | Content axis; the code-focused default excludes prose/docs from ranked results unless `--content docs`/`all` is requested |
| `--matching {literal,all_tokens,any_token}` | `all_tokens` | Exhaustive matching semantics (`--mode exhaustive` only); `literal` treats the whole query as one verbatim substring |
| `--json` | — | JSON output: `{"results": [...], "total_matches": N, "truncated": bool, "freshness": {...}}` |

`--json` reports **`total_matches`** (how many chunks matched the query tokens) and
**`truncated`** (true when only a sample was returned), so agents can tell when a ranked
top-k is incomplete. Every result carries a **`score_sources`** breakdown
(`bm25` / `vector` / `fused` / `weights` / `reranked`) explaining how its score was built.

Ranked envelopes report **`query_time_ms`**, the measured **`model_status`**
(`warm`/`cold`/`disabled`), and the additive **`ranked_path`**
(`hybrid`/`lexical_reduced`/`lexical_degraded`) and **`warmup_state`**. A query
that races model warmup is answered immediately from the labelled
`lexical_reduced` cold path (`degraded_reason: warming`) instead of blocking;
once warm it is `hybrid`. When vector signals are off the envelope also reports
a visible **`degraded_reason`** (`model_disabled`/`model_unavailable`).

`--content code` restricts the pool to source code only, which improves
precision on code questions but does not repair abstract-paraphrase failures
— a query that shares no tokens with the answer still misses it regardless of
scope. It also **excludes config/resource content**; a code-scoped query with
config-shaped intent gets a visible hint on the response envelope pointing at
`--content config`/`--content all`.

Docs search (`--content docs`) is rank-only: prose results carry no per-file
relevance or confidence signal, accepted while the docs corpus stays small
(see [docs/docs_search.md](docs/docs_search.md)); the revisit trigger is the
corpus exceeding 1,000 prose chunks or ~1 MB of indexed docs text.

When the index is stale, a notice like `[stale index: N unindexed change(s) ...]` is
printed to **stderr** (never stdout) for human output; `--json` carries the signal in the
`freshness` object.

### `code-search symbol`

Look up a symbol by fully qualified name (FQN).

```bash
code-search symbol "myproject.auth.jwt.validate_token"
code-search symbol "io.spring.application.UserService.createUser" --json
```

Java method lookups accept a signature so the exact overload resolves:
`code-search symbol "com.example.security.TokenService.generateToken(Map<String,Object>,String)"`.
A bare overloaded name (e.g. `generateToken`) returns all overloads as an `ambiguous`
set, each candidate carrying a `signature {arity, param_types}` object. Unknown,
malformed, or empty names return `found: false` instead of an error.

### `code-search graph`

Traverse the call graph (callers / callees).

```bash
code-search graph "myproject.auth.jwt.validate_token" --depth 2
code-search graph "myproject.auth.jwt.validate_token" --direction callers --json
code-search graph "myproject.auth.jwt.validate_token" --transitive --depth 2
```

| Flag | Default | Description |
|------|---------|-------------|
| `--direction` | `both` | `both`, `callers`, `callees`, or `implements` |
| `--depth N` | `1` | Transitive expansion bound used with `--transitive` (max: 5) |
| `--transitive` | off | Expand transitively to `--depth`; omit for direct-only |
| `--json` | — | JSON output |

`--direction implements` returns the static implementations of the referenced interface method in the `implementations` key (with `callers`/`callees` empty), sharing the dedicated lookup's rule and order.

### `code-search implementations`

Find the static implementations of an interface method (or type).

```bash
code-search implementations "myproject.auth.ArticleRepository.findBySlug"
code-search implementations "myproject.auth.ArticleRepository.findBySlug" --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | — | JSON output |

Each implementation carries its type identity/location, a `relationship` of `direct` or `indirect`, and a `site` for the method that provides it (`inherited: true` names the class that actually declares an inherited method). A reference with no static implementer returns `outcome: "no_static_implementation"` with an explicit explanation instead of a fabricated proxy; an ambiguous reference returns a ranked `candidates` list with nothing auto-selected.

### `code-search metrics`

Query operational metrics.

```bash
code-search metrics
code-search metrics --format json
code-search metrics --format prometheus
```

### `code-search list-languages`

List supported programming languages with file extensions and grammar modules.

```bash
code-search list-languages
```

---

## MCP Server

`code-search` exposes a Model Context Protocol (MCP) stdio server that AI assistants can connect to.

### Starting the server

```bash
code-search serve
```

This runs an infinite loop reading JSON-RPC 2.0 requests from stdin. The server enforces air-gap (outbound sockets blocked) and applies secret redaction to all responses.

> Make sure you have indexed the target codebase before starting the server.

### MCP client configuration

Configure your MCP-compatible client to launch the server. Examples:

**opencode** (`~/.config/opencode/opencode.json` or `./.opencode/opencode.json`):

```json
{
  "mcpServers": {
    "code-search": {
      "command": "code-search",
      "args": ["serve"],
      "env": {
        "CODE_SEARCH_CONTEXT_DIR": "/path/to/your/project/.context",
        "CODE_SEARCH_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "code-search": {
      "command": "code-search",
      "args": ["serve"],
      "env": {
        "CODE_SEARCH_CONTEXT_DIR": "/path/to/your/project/.context"
      }
    }
  }
}
```

### Available tools

| Tool | Description | Key parameters |
|------|-------------|---------------|
| `search` | Hybrid BM25 + vector semantic search | `query`, `limit`, `language`, `include_test_files` |
| `get_symbol_definition` | Look up a symbol by FQN (file-path or conventional dotted) | `symbol` |
| `get_call_neighbors` | Traverse the call graph — upstream callers and downstream callees | `symbol`, `direction`, `max_depth`, `transitive` |
| `get_implementations` | Find the static implementations of an interface method or type | `symbol` |
| `find_related` | Find semantically similar chunks by file + line number | `file_path`, `line_number`, `limit` |

#### `search`

```json
{
  "query": "how is JWT validation implemented",
  "limit": 5,
  "language": null,
  "include_test_files": false
}
```

Returns `{"results": [...], "total_matches": N, "truncated": bool, "freshness": {...}}` —
`results` is an array of chunks with `file_path`, `line_start`, `line_end`, `content`
(redacted), `fqn`, `language`, `score`, `bm25_score`, `vector_score`, `score_sources`,
`is_definition`, `is_test_file`, `redacted_count`. The additive `freshness` object
reports index staleness:
`stale`, `stale_change_count`, `modified_files`, `deleted_files`, `new_files`,
`index_age_s`, `index_status`, `index_root`, `checked_at`.

`total_matches` is the pre-clamp match count and `truncated` is true when only a sample
was returned (so agents never mistake a top-k for the complete match set). Each result's
`score_sources` (`{bm25, vector, fused, weights, reranked}`) explains the score build.

#### `get_symbol_definition`

```json
{
  "symbol": "myproject.auth.jwt.validate_token"
}
```

Returns `found`, `symbol` (fqn, name, kind, `signature`, file_path, line range, docstring,
source_code), optional `parent`, and a top-level additive `freshness` object (see `search`).

Tries conventional dotted FQN first, then file-path FQN as fallback. Java method lookups
accept a signature (e.g. `TokenService.generateToken(Map<String,Object>,String)`) to select
the exact overload; a bare overloaded name returns an `ambiguous` candidate list. Unknown,
malformed, or empty symbols return `found: false` with no error.

#### `get_call_neighbors`

```json
{
  "symbol": "myproject.auth.jwt.validate_token",
  "direction": "both",
  "max_depth": 1,
  "transitive": false
}
```

Returns `symbol`, `callers[]`, `callees[]` — each with `fqn`, `kind`, `file_path`, `line_start`, `call_site_range`, `depth`, and (for CALLS edges) `target_signature` + `overloads` — plus a top-level additive `freshness` object (see `search`). Edges are keyed to the callee's receiver type, so same-named methods on different receivers never conflate. Each neighbor appears once at its minimum depth; `transitive` defaults to `false` (direct-only), and setting it `true` expands to `max_depth`.

#### `get_implementations`

```json
{
  "symbol": "myproject.auth.ArticleRepository.findBySlug"
}
```

Returns `outcome` (`resolved` | `ambiguous` | `not_found` | `no_static_implementation`), the resolved `symbol` and `declaring_type`, an ordered `implementations[]` list (`type`, `site`, `relationship`, `depth`), `candidates[]` when ambiguous, and an `explanation` for a no-static outcome — plus a top-level additive `freshness` object (see `search`). Each `implementations[]` entry reports the implementing type and, for a method query, the `site` that provides it (`inherited: true` and `declaring_type_fqn` when the method comes from a base class). Results are ordered `direct` before `indirect`, declared before inherited, then deterministically by kind/FQN/id. `get_call_neighbors` also accepts `direction: "implements"`, returning the same `implementations` content with empty `callers`/`callees`.

#### `find_related`

```json
{
  "file_path": "src/auth/jwt.py",
  "line_number": 42,
  "limit": 5
}
```

`file_path` may be absolute or project-relative (resolved against the indexed
`index_root`, not the caller's CWD).

Returns `{"results": [...], "freshness": {...}}` — `results` is an array of chunks with
`chunk_id`, `file_path`, `line_start`, `line_end`, `content`, `fqn`, `language`,
`similarity`, plus the additive `freshness` object described under `search`.

### Example JSON-RPC calls

**Request (sent to stdin):**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "function that parses config files",
      "limit": 3
    }
  }
}
```

**Response (from stdout):**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[{\"chunk_id\": 42, \"file_path\": \"src/config/parser.py\", \"line_start\": 10, \"line_end\": 35, \"content\": \"def load_config(path: str) -> dict:\\n    ...\", \"fqn\": \"src.config.parser.load_config\", \"language\": \"python\", \"score\": 0.89, ...}]"
      }
    ]
  }
}
```

---

## AI Agent Usage

When connected as an MCP tool, AI agents should prefer `code-search` over `grep`/`ripgrep` for code *understanding* when the semantic layer is verified healthy. The semantic + structural index gives better results than regex for paraphrase-style questions — but only when the vector layer is actually live (see "Verify vector health" below). For exact-string, counting, or refactor-verification lookups, `grep`/`ripgrep` remain the reliable choice.

### Verify vector health first

Semantic-query claims hold only when the vector layer is healthy. Before trusting natural-language results:

1. Run `code-search search "<query>" --json` and check the envelope's `vector_health` field is `true`.
2. Inspect per-result `vector_score` (non-zero) and `vector_degraded` (`false`).
3. Check the envelope's `ranked_path` (`hybrid`/`lexical_reduced`/`lexical_degraded`), `model_status` (`warm`/`cold`/`disabled`) and `degraded_reason` (`warming`/`model_disabled`/`model_unavailable`). A `lexical_reduced` response means warmup is still in progress; retry shortly for the full hybrid result.
4. If the layer is unavailable (model not loaded, index not rebuilt), fall back to keyword phrasing — `vector_health: false` means the result ordering is lexical-only.

Rebuild the index after major changes so the vector layer reflects the current corpus: `code-search index --path <corpus> --force`.

### When to use which tool

| Task | Tool | Why |
|------|------|-----|
| "Find the function that handles X" | `search` | Natural language query finds relevant code even when you don't know the exact name |
| "What does `validateToken` do?" | `get_symbol_definition` | Resolves the exact definition with full source, docstring, and parent context |
| "Where is `validateToken` called from?" | `get_call_neighbors` | Returns all callers with file paths and line ranges |
| "Find code conceptually similar to this location" | `find_related` | Semantic similarity — finds conceptually related code even with different naming (requires a healthy vector layer; an unavailable layer reports a clear status) |
| "Find all files named config.py" | `grep`/`glob` | Exact filename match is better served by filesystem tools |
| "Find all usages of `DEBUG` constant" | `grep` | Exact string/regex pattern search is still best for grep |
| "Count how many times `foo` appears" | `grep` | Exact counting is a lexical operation, not a search task |
| "Find exact literal string `foo` across codebase" | `search --mode exhaustive` | Exhaustive mode scans all indexed files for literal/token matches; returns exact `total_count` |
| "Search only config files for X" | `search --content config` | Content-type scoping: `code`, `config`, `docs`, `all`, or `code_focused` (default) |

### Typical agent workflow

1. **Verify the layer** — `code-search search "<query>" --json` and confirm `vector_health: true` before relying on semantic ranking
2. **Explore with search** — `search(query="handle user authentication")` to find relevant areas; use short keyword phrases (2-6 words) rather than long prose
3. **Check confidence** — Inspect per-result `confidence` (0-1), `confidence_band` (`high`/`medium`/`low`), and `borderline` flag; low-confidence results should be verified
4. **Dive into symbols** — `get_symbol_definition(symbol="...")` to read the full implementation
5. **Trace the call graph** — `get_call_neighbors(symbol="...", direction="both")` to understand dependencies
6. **Find related code** — `find_related(file_path="...", line_number=...)` to discover sibling patterns
7. **Verify exactly** — use `grep` for exact strings, counting, and refactor checks

### Search modes and content scopes

**Mode** (`--mode` / `mode`):
- `ranked` (default): Hybrid BM25 + vector + RRF fusion with reranking; best for semantic queries
- `exhaustive`: Line-oriented literal/token scan across all indexed files; returns exact `total_count`; use `matching` (`literal`/`all_tokens`/`any_token`) for semantics

**Content scope** (`--content` / `content`):
- `code_focused` (default): Source code only; excludes config/resource/docs
- `code`: Source code only; same filter as `code_focused`
- `config`: Configuration files (YAML, TOML, JSON, XML, properties, etc.)
- `docs`: Prose documentation (Markdown, RST, text)
- `all`: All content types

When a query shaped for config/docs is run under `code`/`code_focused` scope, the response includes a visible hint: *"config content excluded by code scope; use --content config to include"*.

### Production-only search

For production-code questions, exclude test files to avoid test methods displacing the answer:

```bash
code-search search "what happens when a user favorites an article" --no-include-tests
```

The default (`include_tests=true`) keeps test files in results, so production-code answers can rank below keyword-dense test classes; the production-only flag reproduces the same top production answer.

### Pitfalls to avoid

- Don't use `search` (ranked mode) for exact-string, regex, or counting lookups — `grep` or `search --mode exhaustive` is better for those
- Don't assume natural-language results are semantic — verify `vector_health: true` first; a `false` value means lexical-only ranking
- Don't use long prose queries — short keyword phrases (2-6 words) return steadier results
- Don't forget `--no-include-tests` for production-code questions
- Don't use `find_related` when the vector layer is down — it reports a clear "vector layer unavailable" status; `get_symbol_definition` / `get_call_neighbors` remain reliable regardless
- Don't use `get_symbol_definition` with a partial name — use `search` first to find the FQN
- Don't use `get_call_neighbors` with depth > 3 in large codebases — results grow exponentially
- Don't ignore `confidence_band: low` / `borderline: true` on results — these need manual verification
- If `search` returns no results, try simpler/alternative phrasing before falling back to grep
- Don't use `code` scope for config-shaped queries — use `--content config` or `--content all` instead

---

## Configuration

All configuration is via environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `CODE_SEARCH_CONTEXT_DIR` | `.context` | Storage directory path |
| `CODE_SEARCH_LOG_LEVEL` | `WARNING` | Logging verbosity |
| `CODE_SEARCH_EMBEDDING_MODEL` | `potion-code-16m-32d` | Model2Vec model name |
| `CODE_SEARCH_EMBEDDING_DIM` | `32` | Embedding vector dimension |
| `CODE_SEARCH_BM25_K1` | `1.5` | BM25 saturation |
| `CODE_SEARCH_BM25_B` | `0.75` | BM25 length normalization |
| `CODE_SEARCH_RRF_K` | `60` | RRF fusion constant |
| `CODE_SEARCH_MAX_RESULTS` | `50` | Max results per search |
| `CODE_SEARCH_RELEVANCE_THRESHOLD` | `0.05` | Minimum relevance score |
| `CODE_SEARCH_DEFINITION_BOOST` | `1.2` | Definition chunk score multiplier |
| `CODE_SEARCH_NOISE_PENALTY` | `0.5` | Test file score multiplier |
| `CODE_SEARCH_SESSION_TTL_HOURS` | `24` | Session entry TTL |
| `CODE_SEARCH_FILTER_STOPWORDS` | `false` | Filter English stopwords |
| `CODE_SEARCH_FIND_RELATED_LIMIT` | `100` | Max candidates for find_related |
| `CODE_SEARCH_MAX_GRAPH_DEPTH` | `5` | Max call graph traversal depth |

---

## Key points

- The `.context/` directory is your index — **add it to `.gitignore`**
- For incremental re-indexing: `code-search index --incremental`
- For file watching: `code-search index --watch`
- Config lives entirely in env vars — no config files to write
- The MCP server runs under air-gap enforcement (outbound connections blocked)
- Secrets in search results and symbol definitions are automatically redacted
- All queries are recorded in an append-only audit log
- Without the embedding model, search falls back to BM25-only (keyword matching)
