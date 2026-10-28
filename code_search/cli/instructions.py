"""Agent-facing usage instructions for the ``code-search`` CLI.

The ``code-search instructions`` command prints :data:`AGENT_INSTRUCTIONS` so a
coding agent can learn the supported tools, the expected query workflow, and
the failure modes to avoid without parsing the full user manual.
"""

from __future__ import annotations

AGENT_INSTRUCTIONS = """\
# Using code-search with an AI agent

`code-search` is a local, air-gapped code context engine. It combines hybrid
BM25 + vector search with a Tree-sitter symbol and call graph. Prefer it over
`grep`/`ripgrep` when you need to understand code and do not already know the
exact identifier. Use `grep` (or `code-search search --mode exhaustive`) for
exact strings, counts, and mechanical inventories.

## Before the first query

1. Confirm the index and model are healthy: `code-search doctor`.
2. If it does not, build it from the repository root: `code-search index`.
3. Re-index after major changes: `code-search index --force`.
4. Start the daemon once for repeated queries: `code-search start`. One-shot
   invocations also work; they pay the model startup cost each time.
5. If an MCP server is connected, prefer its tools. They return structured JSON
   with a `freshness` object and avoid shell quoting.

## Tools and when to use them

| Question | MCP tool | CLI command |
|---|---|---|
| Where is the code that handles X? | `search` | `code-search search "<query>" --json` |
| What does this symbol do? | `get_symbol_definition` | `code-search symbol <Fqn>` |
| Who calls this? | `get_call_neighbors` | `code-search graph <Fqn>` |
| What implements this interface? | `get_implementations` | `code-search implementations <Fqn>` |
| Similar code? | `find_related` | `code-search find-related <file> --line <n>` |
| How does data flow from A to B? | `query_graph` | `code-search query <question>` |
| Path between two symbols? | `shortest_path` | `code-search path <source> <target>` |
| What changed and what does it affect? | `detect_changes`, `get_impact` | `code-search affected` |
| What is the architecture? | `get_architecture` | `code-search map` |
| What can the graph answer? | `get_graph_schema` | `code-search schema` |
| Was this file indexed completely? | `check_index_coverage` | `code-search coverage <path>` |
| Is the index/model/daemon healthy? | `doctor` | `code-search doctor` |

Read a compact symbol or file view with `code-search view <Fqn|file> --budget
2000`. List declarations with `code-search outline <file>`.

## Search guidance

- Use short keyword phrases (2-6 words), not long prose.
- `--mode ranked` (default) is for paraphrased, semantic questions.
- `--mode exhaustive` scans every indexed file for literal or token matches and
  returns an exact `total_count`; add `--regex` for patterns.
- `--content` selects `code`, `code_focused`, `config`, `docs`, or `all`.
  Omitting it lets query-intent inference choose; override it when the intent is
  wrong.
- Test files are excluded by default. Add `--include-tests` when the test itself
  is the answer.
- Inspect `confidence`, `confidence_band`, and `borderline` on each result. Treat
  `low` and `borderline: true` as candidates that still need verification.

## Verify the vector layer

Semantic ranking depends on a healthy embedding layer. Before trusting ranked
results, run `code-search search "<query>" --json --no-compact` and check:

- `vector_health` is `true`.
- `ranked_path` is `hybrid` (`lexical_reduced` means warmup is in progress;
  retry shortly).
- Per-result `vector_score` is non-zero and `vector_degraded` is `false`.
- `degraded_reason` is absent or `null`.

If `vector_health` is `false`, ordering is lexical-only. Rephrase with keywords
or fall back to exhaustive mode/grep rather than claiming semantic behavior.

## Typical workflow

1. Verify the index and vector health with `code-search doctor`.
2. Run a short keyword search to locate the relevant area.
3. Read the exact definition with `get_symbol_definition` / `code-search symbol`.
4. Trace callers and callees with `get_call_neighbors` /
   `code-search graph`.
5. Follow multi-hop flows with `query_graph` or `code-search query`.
6. Use `find_related` to discover sibling implementations and patterns.
7. Verify exact strings, counts, and refactor completeness with exhaustive
   search or `grep`.

## Pitfalls

- Do not use ranked search for exact strings, regex, or counting.
- Do not assume natural-language results are semantic without checking
  `vector_health`.
- Do not pass a partial symbol name to `get_symbol_definition`; search first to
  find the fully qualified name.
- Do not request call-graph depth above 3 in a large codebase.
- Do not ignore `confidence_band: low` or `borderline: true`.
- Do not use `code` content scope for config-shaped or doc-shaped questions.
- Do not forget that tests are excluded from search by default.
- If a result set is empty, simplify the query before abandoning the tool.

Run `code-search schema` for the queryable graph labels and edge types, and
`code-search instructions` to print this guide again.
"""


def render_agent_instructions() -> str:
    """Return the agent usage guide as Markdown.

    Returns:
        The static Markdown instructions printed by ``code-search instructions``.
    """
    return AGENT_INSTRUCTIONS
