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

### From a local wheel

```bash
pip install dist/code_search-*.whl
```

If you need to build the wheel first, install the `build` package and run
`make build`.

For extra language grammars (Rust, Ruby, Swift, PHP), add the `lang` extra:

```bash
pip install "dist/code_search-0.1.0-py3-none-any.whl[lang]"
```

### From git (pipx)

Installs the CLI into an isolated environment on your `PATH`:

```bash
pipx install --force "git+https://github.com/dhanoopbhaskar/code-search"
```

### From source (development)

```bash
pip install -e /path/to/code-search
```

### From a portable bundle (air-gapped targets)

```bash
# On a machine with network — build the bundle
./scripts/bundle.sh                    # basic bundle (target still needs dependency access)
./scripts/bundle.sh --deps             # with offline dependency wheels

# Copy dist/code-search-*-bundle.tar.gz to the target, then:
tar xzf code-search-*-bundle.tar.gz
cd bundle
python install-from-bundle.py
```

Only the `--deps` bundle contains dependency wheels. The installer also
upgrades `pip` and `wheel` before installing, so a fully offline target needs
those packages available locally.

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
Discovery honours the repository's `.gitignore` files and built-in build/tool
directories by default; `--exclude` patterns are additive. Set
`CODE_SEARCH_RESPECT_GITIGNORE=false` to index ignored paths.

**Useful flags:**

| Flag | Description |
|------|-------------|
| `--path PATH` | Path to codebase root (default: `.`) |
| `--force` | Force a full re-index (a live index lock still aborts) |
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
| `--include-tests` / `--no-include-tests` | `false` | Include/exclude test files (excluded by default; indexed tests are only searchable with `--include-tests`) |
| `--mode {ranked,exhaustive,enumerate}` | `ranked` | Hybrid ranking, exhaustive line scan, or named symbol-kind enumeration (for example "list all controllers") |
| `--content {code,config,docs,all,code_focused}` | intent inference | Content axis; code-shaped queries (including multi-word construct nouns such as `login handler`) default to `code`, documentation-shaped queries widen to `all`, and other queries use `code_focused` (code + config, docs excluded) |
| `--matching {literal,all_tokens,any_token}` | `all_tokens` | Exact matching semantics. Supplying it implies `--mode exhaustive`, so `--matching literal` alone returns the verbatim-substring set and count |
| `--regex` | off | Treat the query as a Python regular expression (`--mode exhaustive` only); invalid patterns return an `invalid_regex` explanation |
| `--no-startup-check` | off | Skip transparent daemon auto-start for this invocation; repeat CLI use is fastest with an already-running `code-search daemon start` |
| `--no-model` | off | Skip the vector model and fuse lexical signals only; the response is labelled `lexical_degraded` |
| `--explain-ranking` | off | Include `score_sources` for every result and print the class/content multipliers and additive boosts behind the ranking |
| `--compact` / `--no-compact` | `--compact` | JSON keeps identifiers, locations, signatures, and short content only. `--no-compact` returns full blocks and the `score_sources` breakdown |
| `--max-snippet-lines N` | `10` in compact JSON | Trim each result to at most N content lines and attach a one-line `signature`; the original line range is preserved |
| `--json` | — | JSON output: `{"results": [...], "total_matches": N, "truncated": bool, "token_savings": {...}, "freshness": {...}}` |

`--json` reports **`total_matches`** (how many chunks matched the query tokens) and
**`truncated`** (true when only a sample was returned), so agents can tell when a ranked
top-k is incomplete. With `--no-compact` (or `--explain-ranking`), every result carries a
**`score_sources`** breakdown (`bm25` / `vector` / `fused` / `weights` / `reranked`)
explaining how its score was built; the compact default omits it.

Ranked envelopes report **`query_time_ms`**, a structured **`model_status`**,
and the additive **`ranked_path`**
(`hybrid`/`lexical_reduced`/`lexical_degraded`) and **`warmup_state`**. On
healthy paths `model_status` is an object whose `state` is
`warm`/`cold`/`initializing` (a cold-start request reports `initializing`);
when the model is disabled or unavailable it is the string `disabled`. The
engine serves a warming query from the labelled `lexical_reduced` cold path
(`degraded_reason: warming`) without blocking; the daemon and MCP server wait
up to `CODE_SEARCH_WARMUP_WAIT_S` (default 5 seconds) for the shared model,
then fall back to the cold path. Once warm the path is `hybrid`. When vector
signals are off the envelope also reports a visible **`degraded_reason`**
(`model_disabled`/`model_unavailable`).

`--content code` restricts the pool to source code only, which improves
precision on code questions but does not repair abstract-paraphrase failures
— a query that shares no tokens with the answer still misses it regardless of
scope. It also **excludes config/resource content**; a code-scoped query with
config-shaped intent gets a visible hint on the response envelope pointing at
`--content config`/`--content all`.

Docs search (`--content docs`) scopes the ranked pool to prose chunks. Prose
results use the same hybrid ranking path as code and carry the same per-result
`confidence`, `confidence_band`, and `borderline` fields.

When the index is stale, a notice like `[stale index: N unindexed change(s) ...]` is
printed to **stderr** (never stdout) for human output; `--json` carries the signal in the
`freshness` object.

### `code-search symbol`

Look up a symbol by fully qualified name (FQN).

```bash
code-search symbol "myproject.auth.jwt.validate_token"
code-search symbol "io.spring.application.UserService.createUser" --json
code-search symbol "ArticleService" --outline
```

Java method lookups accept a signature so the exact overload resolves:
`code-search symbol "com.example.security.TokenService.generateToken(Map<String,Object>,String)"`.
Qualified stored parameter types and Java primitives/boxed types match their
short spellings (`Boolean` = `boolean`, `org.example.Order` = `Order`). A bare
overloaded name (e.g. `generateToken`) returns all overloads as an `ambiguous`
set, each candidate carrying a `signature {arity, param_types}` object, plus a
`try <qualified form>` suggestion. Unknown, malformed, or empty names return
`found: false` instead of an error. Exit codes are `0` resolved, `2` not found,
and `3` ambiguous.

### `code-search view`

Read a symbol or file with a compact outline/body contract.

```bash
code-search view "ArticleService"
code-search view "ArticleService" --outline
code-search view src/main/java/com/example/ArticleService.java --body --max-lines 80
code-search view "ArticleService" --budget 2000 --json
```

Containers longer than 200 lines default to an outline with
`source_omitted: true`; use `--body` to force the source. `--max-lines` caps the
body and `--budget` trims members/source to an approximate token budget.

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
| `--limit N` | `call_graph_limit` (`50`) | Maximum rows per direction; the response's `paging` object reports the exact total and next offset |
| `--offset N` | `0` | Row offset per direction for the next page |
| `--json` | — | JSON output |

`--direction implements` returns the static implementations of the referenced interface method in the `implementations` key (with `callers`/`callees` empty), sharing the dedicated lookup's rule and order.

Receiver-qualified calls resolve through declared field, parameter, and local
types; generic spellings are reduced to the base type (`ProcessContext<Order>`
names `ProcessContext`). Calls through an interface method also carry derived
`CALLS` edges to each implementing method, so path and impact reach the
concrete implementation.

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

### `code-search find-related`

Find chunks semantically similar to the chunk at a file/line anchor — the CLI
counterpart of the MCP `find_related` tool.

```bash
code-search find-related src/auth/service.py --line 42
code-search find-related src/auth/service.py --line 42 --limit 10 --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--line N` | required | Anchor line inside the chunk to compare |
| `--limit N` | `5` | Max related chunks |
| `--json` | — | JSON output (paths relative to the indexed root) |

### `code-search query`

Answer a multi-hop question by traversing the symbol graph from hybrid-search
seeds. The compact answer labels every edge with its provenance.

```bash
code-search query "how does favoriting an article flow from controller to repository"
code-search query "who calls ArticleRepository.save" --depth 3 --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--depth N` | `2` | Traversal depth (max: 4) |
| `--max-nodes N` | `120` | Maximum graph nodes (max: 200) |
| `--edge-types LIST` | `CALLS,INHERITS` | Comma-separated edge types (`CALLS`, `INHERITS`, `IMPLEMENTS`, `REFERENCES`, `USAGE`, `CALL_REFERENCE`, `IMPORTS`) |
| `--token-budget N` | `1500` | Soft output budget; trimmed deterministically |
| `--include-externals` | off | Include unresolved/external callee leaves; by default they are collapsed and counted in `stats.collapsed_externals` |
| `--direction DIR` | `both` | `both`, `inbound` (callers/importers), or `outbound` (callees/imports) |
| `--json` | — | JSON output |

### `code-search path`

Return the shortest directed path between two symbols.

```bash
code-search path "ArticleController.favoriteArticle" "ArticleRepository.save"
code-search path "ArticleController.favoriteArticle" "ArticleRepository.save" --undirected
```

| Flag | Default | Description |
|------|---------|-------------|
| `--undirected` | off | Traverse edges in both directions |
| `--max-hops N` | `6` | Maximum path length (max: 6) |
| `--edge-types LIST` | `CALLS,INHERITS` | Comma-separated edge types (`CALLS`, `INHERITS`, `IMPLEMENTS`, `REFERENCES`, `USAGE`, `CALL_REFERENCE`, `IMPORTS`) |
| `--json` | — | JSON output |

Ambiguous endpoints are refused with their ranked candidates instead of being
guessed.

### `code-search explain`

Explain a symbol: location, signature, incoming/outgoing relations, rationale
comments, and offline documentation links.

```bash
code-search explain "ArticleMutation.favoriteArticle"
code-search explain "ArticleRepository.save" --depth 2 --relations CALLS,INHERITS,IMPORTS
```

| Flag | Default | Description |
|------|---------|-------------|
| `--depth N` | `1` | Ego-graph depth (max: 4) |
| `--relations LIST` | `CALLS,INHERITS` | Comma-separated relations to include (`CALLS`, `INHERITS`, `IMPLEMENTS`, `REFERENCES`, `USAGE`, `CALL_REFERENCE`, `IMPORTS`) |
| `--json` | — | JSON output |

### `code-search affected`

Report changed files and their blast radius, using traversal over callers,
subtypes, importers, or (outbound) dependencies. The response separates
production and test files/symbols and labels each impacted symbol with a
heuristic risk level (`high`/`medium`/`low`).

```bash
code-search affected --since HEAD~1
code-search affected src/main/java/io/spring/core/Article.java --depth 3 --json
code-search affected --base-branch main --scope tests --fixpoint
```

| Flag | Default | Description |
|------|---------|-------------|
| `--since REF` | — | Git ref to diff against; changed paths are added to any explicit paths |
| `--base-branch REF` | — | Base ref to diff against (takes precedence over `--since`) |
| `--scope MODE` | `impact` | `files` (changed set only), `impact` (full blast radius), or `tests` (test files/symbols) |
| `--direction DIR` | `inbound` | `inbound` (dependents), `outbound` (dependencies), or `both` |
| `--depth N` | `3` | Traversal depth (max: 4) |
| `--fixpoint` | — | Walk to closure instead of stopping at `--depth` |
| `--edge-types LIST` | `CALLS,INHERITS` | Symbol edge types to traverse |
| `--no-imports` | — | Do not traverse file-level import edges |
| `--seed-filter MODE` | `all` | `all` seeds every changed symbol; `product` drops test-file seeds |
| `--json` | — | JSON output |

### `code-search map`

Write a deterministic architecture report with god nodes, communities, import
cycles, and suggested questions.

```bash
code-search map --output graph-report.md
code-search map --top 20 --max-communities 8
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output FILE` | — | Write Markdown to this path instead of stdout |
| `--top N` | `15` | Number of god nodes |
| `--max-communities N` | `10` | Maximum communities to report |
| `--aspects LIST` | — | Return only the named bounded sections (`overview`, `structure`, `dependencies`, `hotspots`, `entry_points`, `clusters`, `cycles`, `all`) |
| `--json` | — | JSON output |

### `code-search schema`

Describe the graph before querying it: stored labels, supported and emitted
edge types, resolution tiers, unresolved targets, entry-point counts,
importance availability, coverage gaps, and the index generation.

```bash
code-search schema
code-search schema --diagnostics --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--diagnostics` | — | Include bounded edge-property diagnostics |
| `--limit N` | `100` | Maximum node labels to return |
| `--offset N` | `0` | Node-label offset |
| `--json` | — | JSON output |

### `code-search outline`

List one file's declarations in source order. The exact total is returned even
when the page is bounded.

```bash
code-search outline src/main/java/com/example/article/ArticleService.java
code-search outline src/app.py --kind method,function --include-docstring
```

| Flag | Default | Description |
|------|---------|-------------|
| `--kind LIST` | — | Comma-separated declaration kinds |
| `--limit N` | `200` | Maximum declarations (500 max) |
| `--offset N` | `0` | Declaration offset |
| `--include-docstring` | — | Include stored docstrings |
| `--json` | — | JSON output |

### `code-search symbols`

Search symbols structurally: name/QN regex, kind, file glob, and resolved
degree. Unlike `search`, this does not rank by text similarity.

```bash
code-search symbols --kind class --name-pattern '.*Controller' --include-entry-points
code-search symbols --min-degree 5 --include-connected --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--name-pattern RE` | — | Python regex full-match on the name |
| `--qn-pattern RE` | — | Python regex full-match on the FQN |
| `--kind LIST` | — | Comma-separated declaration kinds |
| `--file-pattern GLOB` | — | Shell glob over the path, or `re:<regex>` |
| `--min-degree N` | — | Minimum resolved total degree |
| `--max-degree N` | — | Maximum resolved total degree |
| `--edge-types LIST` | `CALLS,INHERITS,IMPLEMENTS,REFERENCES,USAGE,CALL_REFERENCE` | Edge types counted for degree |
| `--include-entry-points` | off | Include classified entry points: tests, `main`, constructors, overrides, annotated handlers, and exported top-level declarations (excluded by default) |
| `--include-connected` | off | Attach up to 10 resolved neighbours per symbol |
| `--limit N` | `50` | Maximum symbols (200 max) |
| `--offset N` | `0` | Result offset |
| `--json` | — | JSON output |

### `code-search dead-code`

Report callables with no proven incoming reference from production code.
Candidates exclude entry points and test symbols by default, and each row
reports confidence, test-only usage, and same-name unresolved references.
This is evidence, not permission to delete code.

```bash
code-search dead-code
code-search dead-code --include-tests --json
code-search dead-code --kinds function,method --include-entry-points
```

| Flag | Default | Description |
|------|---------|-------------|
| `--kinds LIST` | `function,method,constructor` | Candidate declaration kinds |
| `--include-entry-points` | off | Include classified entry points |
| `--include-tests` | off | Include test symbols as candidates |
| `--limit N` | `50` | Maximum candidates (200 max) |
| `--offset N` | `0` | Result offset |
| `--json` | — | JSON output |

Confidence is `high` (no incoming edges and no same-name unresolved calls),
`medium` (same-name unresolved calls or test-only usage), or `low` (only
low-confidence incoming evidence). Interface method declarations are not
candidates; they are contracts implemented elsewhere.

### `code-search coverage`

Report where the index has gaps. This is how the CLI distinguishes "no
callers" from "the caller was never indexed".

```bash
code-search coverage
code-search coverage src/app.py
code-search coverage --scope src --json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope PREFIX` | — | Index-relative directory aggregate (repeatable) |
| `--max-rows N` | `500` | Row cap (1000 max) |
| `--json` | — | JSON output |

Statuses are `no_recorded_issue`, `partial`, `unusable`, `skipped`,
`excluded`, `not_indexed`, and `coverage_unavailable`. A clean result means no
gap was recorded for the current generation, not that every reference resolved.

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

This runs an infinite loop reading JSON-RPC 2.0 requests from stdin. The server enforces air-gap (outbound sockets blocked) and redacts secrets in search results, symbol definitions, and `find_related` neighbours.

> Make sure you have indexed the target codebase before starting the server.

### MCP client configuration

Configure your MCP-compatible client to launch the server. Examples:

**opencode** (`~/.config/opencode/opencode.jsonc` or `./opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "code-search": {
      "type": "local",
      "command": ["code-search", "serve"],
      "environment": {
        "CODE_SEARCH_CONTEXT_DIR": "/path/to/your/project/.context",
        "CODE_SEARCH_LOG_LEVEL": "WARNING"
      },
      "enabled": true
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
| `search` | Hybrid BM25 + vector semantic search | `query`, `limit`, `language`, `include_test_files`, `mode`, `content`, `no_model`, `matching`, `regex`, `compact`, `max_snippet_lines` |
| `get_symbol_definition` | Look up a symbol by FQN (file-path or conventional dotted) | `symbol` |
| `get_call_neighbors` | Traverse the call graph — upstream callers and downstream callees | `symbol`, `direction`, `max_depth`, `transitive` |
| `get_implementations` | Find the static implementations of an interface method or type | `symbol` |
| `find_related` | Find semantically similar chunks by file + line number | `file_path`, `line_number`, `limit` |
| `query_graph` | Answer a multi-hop question by bounded graph traversal | `question`, `depth`, `max_nodes`, `token_budget`, `edge_types`, `include_external` |
| `shortest_path` | Shortest path between two symbols | `source`, `target`, `undirected`, `max_hops` |
| `explain_symbol` | Symbol metadata, relations, rationale, and linked docs | `symbol`, `depth`, `relations` |
| `get_impact` | Symbols impacted by changed files | `changed_paths`, `depth` |

#### `search`

```json
{
  "query": "how is JWT validation implemented",
  "limit": 5,
  "language": null,
  "include_test_files": false,
  "compact": true,
  "max_snippet_lines": 20
}
```

Returns `{"results": [...], "total_matches": N, "truncated": bool, "token_savings": {...}, "freshness": {...}}`.
`compact` (default `true`) returns `file_path`, `line_start`, `line_end`, `content`
(a short snippet), `signature`, `content_truncated`, `fqn`, `language`, `score`,
`score_normalized`, `is_definition`, `is_test_file`, and `redacted_count`. Set `compact: false` for the
full block plus `bm25_score`, `vector_score`, and `score_sources`. Paths are relative
to the indexed root. The additive `freshness` object reports index staleness:
`stale`, `stale_change_count`, `modified_files`, `deleted_files`, `new_files`,
`index_age_s`, `index_status`, `index_root`, `checked_at`.

`total_matches` is the pre-clamp match count and `truncated` is true when only a sample
was returned (so agents never mistake a top-k for the complete match set). Ranked
responses also split that count into `production_matches` and `test_matches`, so tests
hidden by the default `include_test_files: false` are still visible in the total.
`score` is the raw ranked score (boosted, so it can exceed 1); `score_normalized`
squashes it monotonically into `[0, 1)` for cross-query comparison. Each result's
`score_sources` (`{bm25, vector, fused, weights, reranked}`) explains the score build.

#### `get_symbol_definition`

```json
{
  "symbol": "myproject.auth.jwt.validate_token"
}
```

Returns `found`, `symbol` (fqn, name, kind, `signature`, file_path, line range, docstring,
source_code), optional `parent`, and a top-level additive `freshness` object (see `search`).

Resolves an exact FQN, conventional dotted FQN, bare/leaf name, or parent-qualified `Class.method` reference first, then falls back to prefix/substring, decomposed sub-word, and edit-distance suggestions. Java method lookups
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

#### `query_graph`

```json
{
  "question": "how does a favorite flow from the controller to the repository",
  "depth": 2,
  "max_nodes": 120,
  "token_budget": 1500,
  "edge_types": "CALLS,INHERITS",
  "include_external": false
}
```

Returns `outcome`, `seeds[]`, `nodes[]`, `edges[]`, `truncated`, `stats`, and
`freshness`. Every edge carries a `confidence` label (`EXTRACTED`, `INFERRED`,
`AMBIGUOUS`, or `UNRESOLVED`) plus its stored `resolution_tier`. Seeds are
reported explicitly so an irrelevant neighbourhood is auditable; `outcome` is
`no_seed` when the ranker and lexical fallback cannot map the question to a
symbol. Each seed carries a `reason` (for example `hybrid search hit #1 (score
1.234)`) so the choice of starting point is auditable.

#### `shortest_path`

```json
{
  "source": "ArticleController.favoriteArticle",
  "target": "ArticleRepository.save",
  "undirected": false,
  "max_hops": 6
}
```

Returns `outcome` (`resolved`, `trivial`, `no_path`, `ambiguous`, `not_found`),
`hops[]` in real edge direction, and ranked `candidates` when an endpoint is
ambiguous. Ambiguous references are never guessed.

#### `explain_symbol`

```json
{
  "symbol": "ArticleRepository.save",
  "depth": 1,
  "relations": "CALLS,INHERITS"
}
```

Returns the symbol identity/location, incoming and outgoing `edges[]`,
`rationale[]` (`NOTE`/`WHY`/`HACK`/`TODO`/`FIXME`/ADR), and `doc_links[]`
produced offline from local embeddings or symbol mentions.

#### `get_impact`

```json
{
  "changed_paths": ["src/main/java/io/spring/core/Article.java"],
  "depth": 3
}
```

Returns `changed_paths`, the changed files' `symbols[]`, reverse-reachable
`impacted[]` nodes grouped by file, `files[]`, and a `summary` with symbol,
file, test, and changed-file counts.

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
        "text": "{\"results\": [{\"chunk_id\": 42, \"file_path\": \"src/config/parser.py\", \"line_start\": 10, \"line_end\": 35, \"content\": \"def load_config(path: str) -> dict:\\n    ...\", \"fqn\": \"src.config.parser.load_config\", \"language\": \"python\", \"score\": 0.89, \"score_normalized\": 0.47}], \"total_matches\": 1, \"truncated\": false, \"vector_health\": true, \"mode\": \"ranked\", \"freshness\": {...}}"
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

1. Run `code-search search "<query>" --json --no-compact` and check the envelope's `vector_health` field is `true`.
2. Inspect per-result `vector_score` (non-zero) and `vector_degraded` (`false`); compact JSON omits both fields.
3. Check the envelope's `ranked_path` (`hybrid`/`lexical_reduced`/`lexical_degraded`), `model_status` (an object with a `state` of `warm`/`cold`/`initializing`, or the string `disabled`) and `degraded_reason` (`warming`/`model_disabled`/`model_unavailable`). A `lexical_reduced` response means warmup is still in progress; retry shortly for the full hybrid result.
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
| "Search only config files for X" | `search --content config` | Content-type scoping: `code`, `config`, `docs`, `all`, or `code_focused` (queries default by intent) |

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
- `enumerate`: Lists the definitions of a named symbol kind (for example "list all controllers")

**Content scope** (`--content` / `content`):
- `code`: Source code only; the inferred default for code-shaped queries
- `code_focused`: Source code plus configuration, docs excluded; the inferred default for configuration-shaped and neutral queries
- `config`: Configuration files (YAML, TOML, JSON, XML, properties, etc.)
- `docs`: Prose documentation (Markdown, RST, text)
- `all`: All content types

When a query shaped for config/docs is run under an excluding `code` scope, the response includes a visible hint such as *"configuration intent detected; configuration is excluded by content scope code; use content scope config to include it"*, and the CLI prints the matching override (`Override with: --content config`) to stderr. Documentation intent gets the analogous `--content all` direction.

### Production-only search

For production-code questions, test files are excluded by default:

```bash
code-search search "what happens when a user favorites an article"
code-search search "validate token" --include-tests   # opt back in
```

The default (`include_tests=false`) removes test files from the result set, so a keyword-dense test class cannot outrank the production code it exercises. `--include-tests` opts them back in; they are still demoted by the ranking pass rather than treated as equal candidates.

### Pitfalls to avoid

- Don't use `search` (ranked mode) for exact-string, regex, or counting lookups — use `search --mode exhaustive` (add `--regex` for patterns) or `grep`
- Don't assume natural-language results are semantic — verify `vector_health: true` first; a `false` value means lexical-only ranking
- Don't use long prose queries — short keyword phrases (2-6 words) return steadier results
- Don't forget that tests are excluded by default; add `--include-tests` when the test itself is the answer
- Don't use `find_related` when the vector layer is down — it reports a clear "vector layer unavailable" status; `get_symbol_definition` / `get_call_neighbors` remain reliable regardless
- Don't use `get_symbol_definition` with a partial name — use `search` first to find the FQN
- Don't use `get_call_neighbors` with depth > 3 in large codebases — results grow exponentially
- Don't ignore `confidence_band: low` / `borderline: true` on results — these need manual verification
- If `search` returns no results, try simpler/alternative phrasing before falling back to grep
- Don't use `code` scope for config-shaped queries — use `--content config` or `--content all` instead

---

## Runtime profiles and output controls

`standard` is the default: legacy index layout and blocking freshness. `small`
enables the compact layout and deferred freshness. Existing indexes are never
migrated implicitly.

```bash
# Write a compact index for a small/medium repository
code-search index --runtime-profile small --index-layout compact --path .

# Search-only index without call-graph edges
code-search index --no-graph --force --path .
code-search graph SomeSymbol --explain-unresolved   # explains missing callers
```

Per-query overrides mirror the environment variables:

```bash
code-search search "validate token" \
  --freshness-mode deferred \
  --paths-only --pretty --allow-weak --wait-for-warm 30
```

`--paths-only` returns only `file_path`, line range, the short symbol name, and
classification fields. `--max-snippet-lines 0` omits content entirely;
`--pretty` restores indented JSON. JSON is compact by default, and `--meta
short` (the default) collapses `freshness` to one value and omits
`model_status`; pass `--meta full` when diagnosing model state. `--allow-weak`
bypasses the extra abstention gate. `--strict` does the opposite: a low-
confidence ranked pool with no definition hit and poor query coverage becomes
`no_match`, with the weak rows preserved under `alternatives`. `--no-daemon`
(formerly `--no-startup-check`) serves one invocation in-process.

`code-search stats --format json` reports the effective profile, layout,
freshness mode, index age, and per-store sizes. It also reports a `graph`
section: edge counts by type and resolution tier, the most frequent unresolved
targets, symbol counts by kind and language, and coverage gaps for the current
`index_generation`. Coverage records distinguish `parse_partial`,
`parse_unusable`, `skipped_read`, and `skipped_oversized` files so an empty
graph answer can be separated from a file that was never indexed. `code-search
start`, `code-search status`, and `code-search doctor` are one-word aliases for
the daemon lifecycle and a combined index/model/daemon diagnosis. `daemon wait
--timeout 30` waits for the model to become warm.

## Evaluation harness

The utility harness reproduces the cold/warm retrieval benchmark on a local
corpus. It is never part of CI: when the corpus is absent it prints `SKIP` and
exits successfully.

```bash
# Index once, then run cold and warm passes and write JSONL
make eval-utility REPO=~/git/baeldung-tutorials

# Equivalent direct invocation
python tests/evaluation/tool_utility_eval.py \
  --repo ~/git/baeldung-tutorials --json-out /tmp/utility.jsonl

# Attribute a warm query's cost to functions and SQLite statements
python tests/evaluation/query_profile.py --repo ~/git/baeldung-tutorials \
  --query ExponentialBackoffRetryFactory --no-model
```

`CODE_SEARCH_EVAL_REPO` sets the default corpus. The JSONL records rank,
hit@1/3/5/10, abstention, latency, output bytes, `ranked_path`, `model_status`,
`warmup_state`, scope, and engine `query_time_ms` per case.

## Configuration

Configuration is environment-variable driven; language definitions can additionally be extended with a JSON file.

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
| `CODE_SEARCH_WARMUP_WAIT_S` | `5.0` | Max seconds the daemon/MCP server wait for model warmup before using the cold path |

---

## Key points

- The `.context/` directory is your index — **add it to `.gitignore`**
- For incremental re-indexing: `code-search index --incremental`
- For file watching: `code-search index --watch`
- Configuration is env-var driven; an optional `language_config.json` (or `CODE_SEARCH_LANGUAGE_CONFIG`) can extend the built-in language definitions
- The MCP server runs under air-gap enforcement (outbound connections blocked)
- Secrets in search results and symbol definitions are automatically redacted
- All queries are recorded in an append-only audit log
- Without the embedding model, search falls back to BM25-only (keyword matching)
