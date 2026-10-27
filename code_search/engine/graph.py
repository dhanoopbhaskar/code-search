"""Graph database — SQLite-backed schema for symbols, code chunks, edges, and metadata.

Manages:
- ``symbols`` — function/class/method/etc. definitions with FQN, location,
  docstring, canonical FQN, entry-point classification, and importance.
- ``graph_edges`` — typed directed edges (``CALLS``, ``IMPLEMENTS``,
  ``INHERITS``, ``REFERENCES``, ``USAGE``, ``CALL_REFERENCE``, ``TESTS``,
  ``IMPORTS``) with JSON resolution evidence.
- ``symbol_degrees`` — derived resolved in/out counts per symbol and edge type.
- ``code_chunks`` — extracted code chunks (AST or fallback) with FTS5 full-text search.
- ``index_coverage`` — per-file parse/skip gaps scoped to an index generation.
- ``index_metadata`` — key-value store for tracking index state and schema versions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from code_search.engine.config import Settings
from code_search.engine.graph_cache import invalidate_adjacency_cache
from code_search.engine.symbol_resolution import (
    parse_reference,
    resolve_reference,
    strip_params,
    symbol_leaf,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 19

#: Graph-semantics version, separate from the SQLite schema version. Bump this
#: when an index must be rebuilt because the meaning of stored rows changed
#: (for example, when new edge types are produced for the same source).
INDEX_FORMAT_VERSION = 1

SYMBOLS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fqn TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK(kind IN (
            'function','class','method','variable',
            'import','interface','enum','type_alias',
            'constructor','field'
        )),
    file_path TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    column_start INTEGER NOT NULL,
    column_end INTEGER NOT NULL,
    docstring TEXT,
    declared_rules TEXT,
    language TEXT NOT NULL,
    conventional_fqn TEXT,
    canonical_fqn TEXT,
    parent_symbol_id INTEGER REFERENCES symbols(id),
    visibility TEXT,
    is_test INTEGER NOT NULL DEFAULT 0,
    is_entry_point INTEGER NOT NULL DEFAULT 0,
    entry_point_reason TEXT,
    importance REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

SYMBOLS_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);",
    # Conventional FQNs are not globally unique: the same package-and-class can
    # appear in more than one source root (fixtures, vendored copies), and a
    # field can share its name with a no-arg accessor. Symbol resolution treats
    # multiple matches as ambiguous, so indexing must not drop them here.
    "CREATE INDEX IF NOT EXISTS idx_symbols_conventional_fqn ON symbols(conventional_fqn);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_file_path ON symbols(file_path);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_symbol_id);",
]

#: Indexes on columns added by the v18 migration. They are created after the
#: migration, never by the base DDL, because an older database does not have
#: the columns yet when ``initialize`` replays ``ALL_DDLS``.
SYMBOL_V18_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_symbols_canonical_fqn ON symbols(canonical_fqn);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_entry_point ON symbols(is_entry_point);",
]

#: Edge types accepted by the schema.
#:
#: ``CALLS``/``INHERITS``/``IMPORTS``/``REFERENCES`` are the original set.
#: ``IMPLEMENTS`` separates a class implementing an interface from ordinary
#: type inheritance, ``CALL_REFERENCE`` records a callable used as a value,
#: ``USAGE`` records a conservative non-call reference, and ``TESTS`` records a
#: test symbol referencing production code.
GRAPH_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "IMPORTS",
    "INHERITS",
    "IMPLEMENTS",
    "REFERENCES",
    "USAGE",
    "CALL_REFERENCE",
    "TESTS",
)

GRAPH_EDGES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    target_symbol_id INTEGER REFERENCES symbols(id),
    edge_type TEXT NOT NULL CHECK(edge_type IN (
        'CALLS','IMPORTS','INHERITS','IMPLEMENTS','REFERENCES',
        'USAGE','CALL_REFERENCE','TESTS'
    )),
    source_range TEXT,
    target_range TEXT,
    resolution_tier TEXT,
    resolved INTEGER NOT NULL DEFAULT 1,
    target_raw TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source_symbol_id, target_symbol_id, edge_type)
);
"""

GRAPH_EDGES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);",
    "CREATE INDEX IF NOT EXISTS idx_edges_source_type ON graph_edges(source_symbol_id, edge_type);",
    "CREATE INDEX IF NOT EXISTS idx_edges_target_type ON graph_edges(target_symbol_id, edge_type);",
]

CODE_CHUNKS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS code_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fqn TEXT,
    -- Repo-relative FQN and path, indexed instead of ``fqn``/``file_path``
    -- so the keyword scorer never sees the checkout location. Nullable: rows
    -- written outside the indexer fall back to the absolute value in the FTS
    -- trigger.
    fqn_rel TEXT,
    path_rel TEXT,
    file_path TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    content TEXT NOT NULL,
    language TEXT NOT NULL,
    is_definition INTEGER NOT NULL DEFAULT 0,
    chunk_type TEXT NOT NULL DEFAULT 'ast',
    chunk_node_type TEXT,
    subwords TEXT,
    declared_rules TEXT,
    tokens_checksum TEXT,
    content_type TEXT NOT NULL DEFAULT 'code',
    is_test INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(file_path, line_start)
);
"""

CODE_CHUNKS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_file_line ON code_chunks(file_path, line_start);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_fqn ON code_chunks(fqn);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_definition ON code_chunks(is_definition);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_is_test_content ON code_chunks(is_test, content_type);",
]

# Persisted corpus statistics. Rebuilt at the end of every full or incremental
# index run so a query can look up only the tokens and prefixes it needs
# instead of scanning every chunk's ``subwords`` column.
SUBWORD_STATS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS subword_stats (
    token TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    doc_count INTEGER NOT NULL,
    PRIMARY KEY(token, language)
);
"""

PREFIX_STATS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS prefix_stats (
    prefix TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    doc_count INTEGER NOT NULL,
    PRIMARY KEY(prefix, language)
);
"""

STATS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_subword_stats_token ON subword_stats(token);",
    "CREATE INDEX IF NOT EXISTS idx_prefix_stats_prefix ON prefix_stats(prefix);",
]

CHUNKS_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    subwords,
    fqn_rel,
    path_rel,
    declared_rules,
    content_type,
    content=code_chunks,
    content_rowid=id
);
"""

# Names of the FTS5 maintenance triggers, dropped and recreated wholesale when
# a full build suspends per-row maintenance.
CHUNKS_FTS_TRIGGER_NAMES = (
    "chunks_fts_ai",
    "chunks_fts_ad",
    "chunks_fts_au",
    "paths_fts_ai",
    "paths_fts_ad",
    "paths_fts_au",
)

# FTS5 external-content maintenance triggers: keep chunks_fts in sync with
# code_chunks on every insert/delete/update so the keyword index cannot drift.
CHUNKS_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON code_chunks BEGIN
        INSERT INTO chunks_fts(rowid, content, subwords, fqn_rel, path_rel, declared_rules,
                               content_type)
        VALUES (new.id, new.content, new.subwords, COALESCE(new.fqn_rel, new.fqn),
                COALESCE(new.path_rel, new.file_path), new.declared_rules, new.content_type);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON code_chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, subwords, fqn_rel, path_rel,
                               declared_rules, content_type)
        VALUES ('delete', old.id, old.content, old.subwords, COALESCE(old.fqn_rel, old.fqn),
                COALESCE(old.path_rel, old.file_path), old.declared_rules, old.content_type);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON code_chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, subwords, fqn_rel, path_rel,
                               declared_rules, content_type)
        VALUES ('delete', old.id, old.content, old.subwords, COALESCE(old.fqn_rel, old.fqn),
                COALESCE(old.path_rel, old.file_path), old.declared_rules, old.content_type);
        INSERT INTO chunks_fts(rowid, content, subwords, fqn_rel, path_rel, declared_rules,
                               content_type)
        VALUES (new.id, new.content, new.subwords, COALESCE(new.fqn_rel, new.fqn),
                COALESCE(new.path_rel, new.file_path), new.declared_rules, new.content_type);
    END;
    """,
]

# File paths are indexed separately from the scored text. FTS5 length
# normalisation counts every token in a row, so keeping the absolute path in
# ``chunks_fts`` made BM25 scores depend on where the repository was checked
# out (a longer ancestor directory silently reweighted every chunk). This
# table is used only for exact filename candidate lookup, where no scoring
# happens.
PATHS_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS paths_fts USING fts5(file_path);
"""

PATHS_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS paths_fts_ai AFTER INSERT ON code_chunks BEGIN
        INSERT INTO paths_fts(rowid, file_path) VALUES (new.id, new.file_path);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS paths_fts_ad AFTER DELETE ON code_chunks BEGIN
        DELETE FROM paths_fts WHERE rowid = old.id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS paths_fts_au AFTER UPDATE ON code_chunks BEGIN
        DELETE FROM paths_fts WHERE rowid = old.id;
        INSERT INTO paths_fts(rowid, file_path) VALUES (new.id, new.file_path);
    END;
    """,
]

METADATA_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS index_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

FILE_CHECKSUMS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS file_checksums (
    file_path TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    size INTEGER,
    file_mtime_ns INTEGER,
    parse_failed INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

# Per-file gaps between "the file exists" and "the graph contains its code".
# Rows are scoped to an index generation: once a new generation is published,
# coverage from the previous generation no longer describes the graph.
INDEX_COVERAGE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS index_coverage (
    file_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    line_ranges TEXT,
    generation TEXT NOT NULL,
    PRIMARY KEY(file_path, kind, generation)
);
"""

INDEX_COVERAGE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_coverage_kind ON index_coverage(kind);",
    "CREATE INDEX IF NOT EXISTS idx_coverage_generation ON index_coverage(generation);",
]

# Derived degree counts, rebuilt at the end of every index run. Counts include
# resolved edges only: an unresolved reference is evidence, not a proven
# relationship, so dead-code and degree filters must never treat it as one.
SYMBOL_DEGREES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS symbol_degrees (
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    in_count INTEGER NOT NULL DEFAULT 0,
    out_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(symbol_id, edge_type)
);
"""

SYMBOL_DEGREES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_symbol_degrees_filter "
    "ON symbol_degrees(edge_type, in_count, out_count);",
]

# SQLite treats NULL values as distinct in a UNIQUE constraint, so unresolved
# edges (``target_symbol_id IS NULL``) are not deduplicated by the table-level
# UNIQUE(source_symbol_id, target_symbol_id, edge_type). This partial unique
# index closes that gap without affecting resolved edges, which may legitimately
# share raw text (for example two overloads called with the same spelling).
UNRESOLVED_EDGE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique_unresolved
ON graph_edges(source_symbol_id, edge_type, COALESCE(target_raw, ''))
WHERE target_symbol_id IS NULL;
"""

# File/module-level edge table. Kept separate from ``graph_edges`` so imports
# between files can be represented without a symbol node or a schema CHECK
# rebuild. ``source_path``/``target_path`` are index-root-relative POSIX paths.
MODULE_EDGES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS module_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    target_path TEXT,
    relation TEXT NOT NULL,
    target_raw TEXT,
    resolved INTEGER NOT NULL DEFAULT 1,
    source_range TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

MODULE_EDGES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_module_edges_source ON module_edges(source_path);",
    "CREATE INDEX IF NOT EXISTS idx_module_edges_target ON module_edges(target_path);",
    "CREATE INDEX IF NOT EXISTS idx_module_edges_relation ON module_edges(relation);",
    # Expression index: UNIQUE would not deduplicate NULL target paths.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_module_edges_unique "
    "ON module_edges(source_path, relation, COALESCE(target_path, ''), "
    "COALESCE(target_raw, ''));",
]

# Rationale comments (NOTE/WHY/HACK/TODO/FIXME/ADR) linked to the nearest
# enclosing symbol. Rationale is searchable through ``rationale_fts`` and
# surfaced by ``explain_symbol``.
SYMBOL_RATIONALE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS symbol_rationale (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(symbol_id, file_path, line_start, kind)
);
"""

SYMBOL_RATIONALE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rationale_symbol ON symbol_rationale(symbol_id);",
    "CREATE INDEX IF NOT EXISTS idx_rationale_file ON symbol_rationale(file_path);",
]

RATIONALE_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS rationale_fts USING fts5(
    text,
    content=symbol_rationale,
    content_rowid=id
);
"""

RATIONALE_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS rationale_fts_ai AFTER INSERT ON symbol_rationale BEGIN
        INSERT INTO rationale_fts(rowid, text) VALUES (new.id, new.text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rationale_fts_ad AFTER DELETE ON symbol_rationale BEGIN
        INSERT INTO rationale_fts(rationale_fts, rowid, text) VALUES ('delete', old.id, old.text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rationale_fts_au AFTER UPDATE ON symbol_rationale BEGIN
        INSERT INTO rationale_fts(rationale_fts, rowid, text) VALUES ('delete', old.id, old.text);
        INSERT INTO rationale_fts(rowid, text) VALUES (new.id, new.text);
    END;
    """,
]

# Offline links between documentation/config chunks and code chunks, produced
# at index time from local embeddings and deterministic symbol mentions.
DOC_LINKS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS doc_links (
    doc_chunk_id INTEGER NOT NULL,
    code_chunk_id INTEGER NOT NULL,
    score REAL NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (doc_chunk_id, code_chunk_id)
);
"""

DOC_LINKS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_doc_links_code ON doc_links(code_chunk_id);",
]

ALL_DDLS = [
    SYMBOLS_TABLE_DDL,
    *SYMBOLS_INDEXES,
    GRAPH_EDGES_TABLE_DDL,
    *GRAPH_EDGES_INDEXES,
    CODE_CHUNKS_TABLE_DDL,
    *CODE_CHUNKS_INDEXES,
    SUBWORD_STATS_TABLE_DDL,
    PREFIX_STATS_TABLE_DDL,
    *STATS_INDEXES,
    CHUNKS_FTS_DDL,
    *CHUNKS_FTS_TRIGGERS,
    PATHS_FTS_DDL,
    *PATHS_FTS_TRIGGERS,
    FILE_CHECKSUMS_TABLE_DDL,
    INDEX_COVERAGE_TABLE_DDL,
    *INDEX_COVERAGE_INDEXES,
    SYMBOL_DEGREES_TABLE_DDL,
    *SYMBOL_DEGREES_INDEXES,
    MODULE_EDGES_TABLE_DDL,
    *MODULE_EDGES_INDEXES,
    SYMBOL_RATIONALE_TABLE_DDL,
    *SYMBOL_RATIONALE_INDEXES,
    RATIONALE_FTS_DDL,
    *RATIONALE_FTS_TRIGGERS,
    DOC_LINKS_TABLE_DDL,
    *DOC_LINKS_INDEXES,
    METADATA_TABLE_DDL,
]


def read_source_slice(file_path: str, line_start: int | None, line_end: int | None) -> str:
    """Read the slice of *file_path* spanning rows ``line_start..line_end``.

    ``line_start``/``line_end`` are 0-based AST rows (matching ``line_start``/
    ``line_end`` in ``symbols``/``code_chunks``). Returns ``""`` when the file
    is missing or the range is unavailable.
    """
    if not file_path or line_start is None or line_end is None:
        return ""
    try:
        with Path(file_path).open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    start = max(0, line_start)
    end = min(max(0, len(lines) - 1), line_end)
    return "".join(lines[start : end + 1]).rstrip("\n")


def _strip_params(name: str) -> str:
    """Strip a trailing ``(...)`` parameter list from a name."""
    return strip_params(name)


def _symbol_leaf(query: str) -> str:
    """Extract the bare symbol name from a query (dotted, param, or path forms)."""
    return symbol_leaf(query)


def _levenshtein(a: str | list[str], b: str | list[str]) -> int:
    """Compute the edit distance between two sequences (case-insensitive).

    Accepts strings or token lists; a token list compares whole tokens so
    ``["validate", "token"]`` vs ``["is", "token", "valid"]`` scores 2.
    """
    if isinstance(a, str) and isinstance(b, str):
        a, b = a.lower(), b.lower()
    if isinstance(a, list) and isinstance(b, list):
        a = [t.lower() for t in a]
        b = [t.lower() for t in b]
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    return prev[-1]


def _decompose_leaf(leaf: str) -> list[str]:
    """Split an identifier leaf into lowercased sub-words (camel/snake/acronym).

    Mirrors ``identify_subwords`` without importing search.py (which imports
    graph.py), avoiding a circular import.
    """
    import re

    parts = re.split(r"(?<=[a-z0-9])(?=[A-Z])|_|(?<=[A-Z])(?=[A-Z][a-z])", leaf)
    return [p.lower() for p in parts if p]


def _edge_properties_json(value: Any) -> str:
    """Serialise edge properties to a JSON object string.

    ``properties`` is stored as ``TEXT NOT NULL DEFAULT '{}'`` so a consumer
    can always parse it. A non-dict value is replaced with an empty object
    rather than written as an invalid shape.
    """
    if not isinstance(value, dict):
        return "{}"
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return "{}"


def _call_graph_page(returned: int, total: int, limit: int, offset: int) -> dict[str, Any]:
    """Return one direction's paging metadata for a call-graph page."""
    has_more = offset + returned < total
    return {
        "returned": returned,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
    }


def _resolve_symbol_candidates(
    conn: sqlite3.Connection,
    query: str,
    suggest_edit_distance: int = 2,
) -> list[dict[str, Any]]:
    """Return candidate symbol rows loosely matching *query*, with parent info.

    Fallback stages, in order:
      1. exact FQN / bare name / leaf name / ``::name`` suffix / conventional-FQN
         suffix (the existing exact path);
      2. prefix / substring name match (``TokenSer`` -> ``TokenService``);
      3. decomposed sub-word match (``token valid`` matches ``isTokenValid``);
      4. edit-distance ≤ ``suggest_edit_distance`` (guarded to leaf length ≥ 3)
         producing best-effort "did you mean" suggestions with an
         ``edit_distance`` field.
    """
    leaf = _symbol_leaf(query)
    if not query.strip() or not leaf.strip():
        # An empty/whitespace reference must report not_found rather than
        # matching every ``::``-bearing FQN through the empty suffix pattern.
        return []
    # Stage 1a: indexed exact lookups. These use the unique/plain indexes and
    # never a leading-wildcard LIKE, which would force a full symbol scan.
    exact_rows = conn.execute(
        "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
        "p.fqn AS parent_fqn "
        "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
        "WHERE s.fqn = ? OR s.name = ? OR s.name = ? OR s.conventional_fqn = ? "
        "ORDER BY s.id LIMIT 100;",
        (query, query, leaf, query),
    ).fetchall()
    if exact_rows:
        return [dict(r) for r in exact_rows]

    # Stage 1b: suffix forms that cannot be indexed (``Class::member`` and
    # conventional-FQN suffixes). Only reached when no exact row exists.
    suffix_rows = conn.execute(
        "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
        "p.fqn AS parent_fqn "
        "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
        "WHERE s.fqn LIKE '%::' || ? OR s.conventional_fqn LIKE '%' || ? "
        "ORDER BY s.id LIMIT 100;",
        (query, query),
    ).fetchall()
    if suffix_rows:
        return [dict(r) for r in suffix_rows]

    # Stage 2: prefix / substring name match
    if len(leaf) >= 2:
        prefix_rows = conn.execute(
            "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
            "p.fqn AS parent_fqn "
            "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
            "WHERE s.name LIKE ? OR s.name LIKE ? "
            "ORDER BY s.id LIMIT 25;",
            (f"{leaf}%", f"%{leaf}%"),
        ).fetchall()
        if prefix_rows:
            return [dict(r) for r in prefix_rows]

    # Stage 3: decomposed sub-word match (query sub-words all present in name)
    if leaf and leaf.lower() not in leaf and len(leaf) >= 3:
        subwords = _decompose_leaf(leaf)
        if len(subwords) >= 2:
            all_rows = conn.execute(
                "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
                "p.fqn AS parent_fqn "
                "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
                "ORDER BY s.id LIMIT 2000;",
            ).fetchall()
            matched: list[dict[str, Any]] = []
            for row in all_rows:
                name_subwords = _decompose_leaf(row["name"] or "")
                if all(w in name_subwords for w in subwords):
                    matched.append(dict(row))
            if matched:
                return matched[:25]

    # Stage 4: "did you mean" suggestions via edit distance, guarded to leaf
    # length >= 3 and capped at ``suggest_edit_distance``. Multi-sub-word
    # queries (camelCase/snake_case identifiers) compare decomposed sub-word
    # sequences (``validateToken`` -> ``isTokenValid`` at distance 2); plain
    # single-word queries compare the raw name (true typo tolerance only).
    if len(leaf) >= 3:
        query_subwords = _decompose_leaf(leaf)
        use_sequence = len(query_subwords) >= 2
        name_rows = conn.execute(
            "SELECT DISTINCT name FROM symbols ORDER BY name LIMIT 5000;"
        ).fetchall()
        scored: list[tuple[int, int, str]] = []
        for row in name_rows:
            name = row["name"] or ""
            if not name:
                continue
            if use_sequence:
                dist = _levenshtein(query_subwords, _decompose_leaf(name))
                shared = len(set(query_subwords) & set(_decompose_leaf(name)))
            else:
                dist = _levenshtein(leaf, name)
                shared = 0
            if dist <= suggest_edit_distance:
                scored.append((dist, -shared, name))
        if scored:
            scored.sort(key=lambda pair: (pair[0], pair[1], pair[2]))
            top_names = [name for _dist, _shared, name in scored[:10]]
            placeholders = ",".join("?" for _ in top_names)
            suggestion_rows = conn.execute(
                f"SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
                f"p.fqn AS parent_fqn "
                f"FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
                f"WHERE s.name IN ({placeholders}) "
                f"ORDER BY s.id LIMIT 25;",
                top_names,
            ).fetchall()
            results = [dict(r) for r in suggestion_rows]
            dist_map = {name: dist for dist, _shared, name in scored}
            rank_map = {name: rank for rank, (_d, _s, name) in enumerate(scored)}
            for r in results:
                r["edit_distance"] = dist_map.get(r.get("name", ""), 0)
            # Re-sort by the scored order (distance, then shared-subword
            # overlap, then name) so the best "did you mean" suggestion is first.
            results.sort(key=lambda r: rank_map.get(r.get("name", ""), 10**9))
            return results

    return []


def _rank_symbol_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    max_candidates: int = 10,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    """Rank candidates to ``(unique_symbol, candidates, kind)`` for *query*.

    Delegates to the pure :func:`code_search.engine.symbol_resolution.resolve_reference`
    policy: exact FQN -> exact conventional FQN -> unique bare leaf ->
    exact parent scope resolve only when exactly one declaration matches; any
    remaining multi-match yields a ranked, evidence-carrying disambiguation
    list (never an auto-selected declaration). The ambiguous list is bounded by
    ``max_candidates``.
    """
    result = resolve_reference(parse_reference(query), candidates, max_candidates=max_candidates)
    return result.symbol, result.candidates, result.kind


def _signature_from_fqn(src: str | None) -> dict[str, Any] | None:
    """Parse a normalized ``{arity, param_types}`` signature from a stored FQN.

    Mirrors ``symbols.normalize_signature`` without importing symbols.py (which
    imports this module), avoiding a circular import. Used to attach
    ``target_signature``/``overloads`` to call-graph edges.
    """
    if not src or "(" not in src:
        return None
    open_idx = src.find("(")
    close_idx = src.rfind(")")
    if close_idx == -1 or close_idx < open_idx:
        return None
    body = src[open_idx + 1 : close_idx]
    out: list[str] = []
    depth = 0
    for ch in body:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    param_types = [t.strip() for t in "".join(out).split(",")]
    param_types = [t for t in param_types if t]
    return {"arity": len(param_types), "param_types": param_types}


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Compact candidate dict for disambiguation responses.

    Carries the existing identity/location fields plus the additive ranking
    ``evidence`` and ``deprecated`` fields attached by the ranking policy.
    Suggestion-level near-misses keep ``edit_distance`` (and no policy
    evidence).
    """
    summary = {
        "fqn": row.get("fqn"),
        "conventional_fqn": row.get("conventional_fqn"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "file_path": row.get("file_path"),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
        "parent_name": row.get("parent_name"),
    }
    if row.get("signature") is not None:
        summary["signature"] = row.get("signature")
    if row.get("edit_distance") is not None:
        summary["edit_distance"] = row.get("edit_distance")
    if row.get("deprecated") is not None:
        summary["deprecated"] = bool(row.get("deprecated"))
    evidence = row.get("evidence")
    if evidence is not None:
        summary["evidence"] = list(evidence)
    return summary


class GraphDatabase:
    """Thread-safe SQLite database for the code graph schema.

    Provides per-thread connections (via ``threading.local()``), WAL journaling,
    and a dedicated ``write_transaction`` context manager with serialised writes.
    """

    def __init__(self, db_path: Path, settings: Settings | None = None) -> None:
        """Initialize a thread-safe connection manager for *db_path*.

        Connections are created lazily per-thread; the schema is created by
        calling :meth:`initialize` explicitly.

        Args:
            db_path: Filesystem path of the SQLite database file.
            settings: Engine settings (e.g. ``lock_timeout``); defaults to
                ``Settings.from_env()``.
        """
        self._db_path = db_path
        self._settings = settings or Settings.from_env()
        self._local = threading.local()
        self._write_lock = threading.Lock()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return the current thread's connection, creating it if needed."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return cast(sqlite3.Connection, self._local.conn)

    def _create_connection(self) -> sqlite3.Connection:
        """Open a fresh SQLite connection with WAL, foreign keys, and Row factory.

        ``synchronous=NORMAL`` drops the per-commit fsync that WAL's default
        ``FULL`` setting issues. The database cannot be corrupted by a crash;
        only the durability of the last in-flight transaction is traded away,
        which is acceptable for a rebuildable index.

        The connection also receives the graph workload's pragmas: a bounded
        page cache, a memory-mapped read window, in-memory temporary tables,
        and a busy timeout. All are configurable so a constrained deployment
        can lower the memory footprint.

        Returns:
            A configured ``sqlite3.Connection`` usable from any thread
            (``check_same_thread=False``).
        """
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(f"PRAGMA busy_timeout = {int(self._settings.lock_timeout * 1000)};")
        if self._settings.sqlite_cache_kib > 0:
            conn.execute(f"PRAGMA cache_size = -{int(self._settings.sqlite_cache_kib)};")
        if self._settings.sqlite_mmap_bytes > 0:
            conn.execute(f"PRAGMA mmap_size = {int(self._settings.sqlite_mmap_bytes)};")
        if self._settings.sqlite_temp_store_memory:
            conn.execute("PRAGMA temp_store = MEMORY;")
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def db_path(self) -> Path:
        """Return the database file path (the adjacency-cache key component)."""
        return self._db_path

    def initialize(self) -> None:
        """Create all tables, indexes, and triggers; record or validate schema version."""
        with self._write_lock:
            conn = self._create_connection()
            try:
                # Additive v15 migration must run before the composite index on
                # (is_test, content_type) is created on an existing database.
                columns = conn.execute("PRAGMA table_info(code_chunks);").fetchall()
                column_names = {col["name"] for col in columns} if columns else set()
                if columns and "is_test" not in column_names:
                    conn.execute(
                        "ALTER TABLE code_chunks ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0;"
                    )
                if columns and "fqn_rel" not in column_names:
                    # The FTS triggers below reference these columns, so they
                    # must exist before the schema DDL runs. Migration v19
                    # backfills them and rebuilds the keyword index.
                    conn.execute("ALTER TABLE code_chunks ADD COLUMN fqn_rel TEXT;")
                    conn.execute("ALTER TABLE code_chunks ADD COLUMN path_rel TEXT;")
                elif columns and "path_rel" not in column_names:
                    conn.execute("ALTER TABLE code_chunks ADD COLUMN path_rel TEXT;")
                for ddl in ALL_DDLS:
                    conn.execute(ddl)
                row = conn.execute(
                    "SELECT value FROM index_metadata WHERE key = 'index_version';"
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO index_metadata (key, value) VALUES (?, ?);",
                        ("index_version", str(SCHEMA_VERSION)),
                    )
                else:
                    existing_version = int(row["value"])
                    if existing_version < SCHEMA_VERSION:
                        logger.warning(
                            "Schema version mismatch: existing=%d, required=%d. Running migration.",
                            existing_version,
                            SCHEMA_VERSION,
                        )
                        if existing_version == 2:
                            conn.execute("ALTER TABLE code_chunks DROP COLUMN embedding;")
                        if existing_version == 3:
                            conn.execute(
                                "CREATE TABLE IF NOT EXISTS symbols_v4 ("
                                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                                "fqn TEXT NOT NULL UNIQUE,"
                                "name TEXT NOT NULL,"
                                "kind TEXT NOT NULL "
                                "CHECK(kind IN ("
                                "'function','class','method','variable',"
                                "'import','interface','enum','type_alias',"
                                "'constructor','field'"
                                ")),"
                                "file_path TEXT NOT NULL,"
                                "line_start INTEGER NOT NULL,"
                                "line_end INTEGER NOT NULL,"
                                "column_start INTEGER NOT NULL,"
                                "column_end INTEGER NOT NULL,"
                                "docstring TEXT,"
                                "language TEXT NOT NULL,"
                                "parent_symbol_id INTEGER REFERENCES symbols(id),"
                                "created_at TEXT NOT NULL DEFAULT (strftime("
                                "'%Y-%m-%dT%H:%M:%fZ','now')),"
                                "updated_at TEXT NOT NULL DEFAULT (strftime("
                                "'%Y-%m-%dT%H:%M:%fZ','now'))"
                                ");"
                            )
                            conn.execute("INSERT INTO symbols_v4 SELECT * FROM symbols;")
                            conn.execute("DROP TABLE symbols;")
                            conn.execute("ALTER TABLE symbols_v4 RENAME TO symbols;")
                            conn.execute(
                                "CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);"
                            )
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS "
                                "idx_symbols_file_path ON symbols(file_path);"
                            )
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);"
                            )
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS "
                                "idx_symbols_parent ON symbols(parent_symbol_id);"
                            )
                        if existing_version == 4:
                            conn.execute("ALTER TABLE symbols ADD COLUMN conventional_fqn TEXT;")
                            conn.execute(
                                "CREATE UNIQUE INDEX IF NOT EXISTS "
                                "idx_symbols_conventional_fqn ON symbols(conventional_fqn);"
                            )
                        if existing_version <= 6:
                            self._migrate_v7(conn)
                        if existing_version <= 7:
                            self._migrate_v8(conn)
                        if existing_version <= 9:
                            self._migrate_v9(conn)
                        if existing_version <= 10:
                            self._migrate_v10(conn)
                        if existing_version <= 11:
                            self._migrate_v11(conn)
                        if existing_version <= 13:
                            self._migrate_v14(conn)
                        if existing_version <= 15:
                            self._migrate_v16(conn)
                        if existing_version <= 16:
                            self._migrate_v17(conn)
                        if existing_version <= 17:
                            self._migrate_v18(conn)
                        if existing_version <= 18:
                            self._migrate_v19(conn)
                        conn.execute(
                            "UPDATE index_metadata SET value = ? WHERE key = 'index_version';",
                            (str(SCHEMA_VERSION),),
                        )
                        conn.execute(
                            "UPDATE index_metadata SET value = 'stale' WHERE key = 'index_status';"
                        )
                # Self-heal derived indexes: a database written by an older or
                # interrupted build may carry a keyword index without the
                # relative-FQN column or lack the separate path index. Rebuild
                # both from the base table so path/FQN lookup never silently
                # degrades.
                fts_columns = {
                    r["name"] for r in conn.execute("PRAGMA table_info(chunks_fts);").fetchall()
                }
                paths_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'paths_fts';"
                ).fetchone()
                if "path_rel" not in fts_columns or paths_table is None:
                    logger.info("Rebuilding keyword indexes for the relative-path layout")
                    self._backfill_relative_fqns(conn)
                    self._rebuild_scored_fts(conn)
                self._ensure_unresolved_edge_index(conn)
                self._ensure_v18_indexes(conn)
                self._drop_redundant_edge_indexes(conn)
                conn.commit()
            finally:
                conn.close()
            self._local.conn = None
            invalidate_adjacency_cache(self._db_path)

    def _drop_redundant_edge_indexes(self, conn: sqlite3.Connection) -> None:
        """Drop edge indexes whose columns are a prefix of a composite index.

        ``idx_edges_source`` is covered by ``idx_edges_source_type`` (and by
        the unique ``(source_symbol_id, target_symbol_id, edge_type)`` index),
        and ``idx_edges_target`` is covered by ``idx_edges_target_type``.
        Keeping the single-column indexes only adds write amplification and
        disk use. Queries that used to name them now name the composite index
        explicitly, so the planner does not fall back to a table scan.
        """
        for name in ("idx_edges_source", "idx_edges_target"):
            conn.execute(f"DROP INDEX IF EXISTS {name};")

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, Any, None]:
        """Yield the calling thread's read connection in a context manager.

        No commit/rollback is performed on exit; use :meth:`write_transaction`
        for writes.
        """
        yield self._conn

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Connection, Any, None]:
        """Yield a serialised write connection, committing on clean exit.

        Writes are serialised across threads by a module-level lock. On
        exception the transaction is rolled back and re-raised; the temporary
        connection is always closed afterwards.

        Yields:
            A connection whose changes are committed atomically on clean exit.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                yield conn
                conn.commit()
                invalidate_adjacency_cache(self._db_path)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
                self._local.conn = None

    @contextmanager
    def write_connection(self) -> Generator[sqlite3.Connection, Any, None]:
        """Yield a serialised writer connection that spans many commits.

        Unlike :meth:`write_transaction`, which opens, commits, and closes a
        fresh connection per call, this opens one connection for the caller's
        whole batch and leaves commit boundaries to the caller. ``journal_mode``
        is a persistent database property, so re-issuing it per transaction is
        pure overhead; reusing one connection avoids it. The connection is
        committed on clean exit (idempotent when the caller already committed)
        and rolled back on exception.

        Yields:
            A connection the caller commits explicitly between batches.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                yield conn
                conn.commit()
                invalidate_adjacency_cache(self._db_path)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
                self._local.conn = None

    def set_fts_triggers(self, enabled: bool) -> None:
        """Enable or disable the keyword and path FTS maintenance triggers.

        Full builds suspend the triggers while bulk-inserting ``code_chunks``
        and rebuild the keyword indexes wholesale afterwards, so the per-row
        trigger work is redundant. Incremental indexing relies on the triggers
        and keeps them enabled. Dropping is idempotent and self-heals on the
        next :meth:`initialize` (the triggers are recreated by the schema DDL).

        Args:
            enabled: ``True`` to (re)create the triggers, ``False`` to drop them.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                for name in CHUNKS_FTS_TRIGGER_NAMES:
                    conn.execute(f"DROP TRIGGER IF EXISTS {name};")
                if enabled:
                    for trigger in [*CHUNKS_FTS_TRIGGERS, *PATHS_FTS_TRIGGERS]:
                        conn.execute(trigger)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
                self._local.conn = None

    def _migrate_v7(self, conn: sqlite3.Connection) -> None:
        """Migrate a v6 database to schema v7.

        Adds ``code_chunks.subwords`` and ``graph_edges.resolution_tier`` and
        recreates the ``chunks_fts`` FTS5 external-content virtual table with
        the new ``subwords`` column (FTS5 virtual tables cannot be ALTERed, so
        the table is dropped and recreated — triggers too — then repopulated).
        Also drops the old ``CHECK(source_symbol_id != target_symbol_id)`` so
        genuine recursive self-call edges can be preserved.
        """
        logger.info("Migrating schema v6 -> v7")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(code_chunks);").fetchall()}
        if "subwords" not in cols:
            conn.execute("ALTER TABLE code_chunks ADD COLUMN subwords TEXT;")
        edge_cols = {r["name"] for r in conn.execute("PRAGMA table_info(graph_edges);").fetchall()}
        if "resolution_tier" not in edge_cols:
            conn.execute("ALTER TABLE graph_edges ADD COLUMN resolution_tier TEXT;")
        self._drop_edges_self_check(conn)
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ai;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ad;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_au;")
        conn.execute("DROP TABLE IF EXISTS chunks_fts;")
        conn.execute(CHUNKS_FTS_DDL)
        for trigger in CHUNKS_FTS_TRIGGERS:
            conn.execute(trigger)
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")

    def _migrate_v8(self, conn: sqlite3.Connection) -> None:
        """Migrate a v7 (or older) database to schema v8.

        Adds the nullable ``size``/``file_mtime_ns`` stat-baseline columns to
        ``file_checksums`` for the freshness stat fast-path. Existing rows keep
        ``NULL`` baselines and are self-healed on the first freshness scan —
        no data rewrite, no index rebuild. The caller sets ``index_status`` to
        the lifecycle value ``stale`` (re-index recommended) as part of the
        shared migration path.
        """
        logger.info("Migrating schema v7 -> v8")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(file_checksums);").fetchall()}
        if "size" not in cols:
            conn.execute("ALTER TABLE file_checksums ADD COLUMN size INTEGER;")
        if "file_mtime_ns" not in cols:
            conn.execute("ALTER TABLE file_checksums ADD COLUMN file_mtime_ns INTEGER;")

    def _migrate_v9(self, conn: sqlite3.Connection) -> None:
        """Migrate a v8 (or older) database to schema v9.

        Adds the nullable ``declared_rules`` column to ``code_chunks`` (rule
        text extracted from annotations/decorators at index time) and rebuilds
        ``chunks_fts`` with the new ``declared_rules`` FTS5 column so the
        keyword index stays at parity with the base table. FTS5 virtual tables
        cannot be ALTERed, so the table and its triggers are dropped and
        recreated with the fifth column, then repopulated.
        """
        logger.info("Migrating schema v8 -> v9")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(code_chunks);").fetchall()}
        if "declared_rules" not in cols:
            conn.execute("ALTER TABLE code_chunks ADD COLUMN declared_rules TEXT;")
        sym_cols = {r["name"] for r in conn.execute("PRAGMA table_info(symbols);").fetchall()}
        if "declared_rules" not in sym_cols:
            conn.execute("ALTER TABLE symbols ADD COLUMN declared_rules TEXT;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ai;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ad;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_au;")
        conn.execute("DROP TABLE IF EXISTS chunks_fts;")
        conn.execute(CHUNKS_FTS_DDL)
        for trigger in CHUNKS_FTS_TRIGGERS:
            conn.execute(trigger)
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")

    def _migrate_v11(self, conn: sqlite3.Connection) -> None:
        """Migrate a v11 (or older) database to the v12 schema.

        Adds ``code_chunks.content_type`` (the code|config|docs content axis),
        ``graph_edges.resolved`` (default true) and ``graph_edges.target_raw``
        (nullable raw callee text) for unresolved/external callees, and makes
        ``graph_edges.target_symbol_id`` nullable so a ``resolved: 0`` edge can
        carry ``NULL`` target with its raw reference text. FTS5 virtual tables
        cannot be ALTERed, so ``chunks_fts`` is rebuilt with the new
        ``content_type`` column for index parity.
        """
        logger.info("Migrating schema v11 -> v12")
        chunk_cols = {r["name"] for r in conn.execute("PRAGMA table_info(code_chunks);").fetchall()}
        if "content_type" not in chunk_cols:
            conn.execute(
                "ALTER TABLE code_chunks ADD COLUMN content_type TEXT NOT NULL DEFAULT 'code';"
            )
        edge_cols = {r["name"] for r in conn.execute("PRAGMA table_info(graph_edges);").fetchall()}
        if "resolved" not in edge_cols:
            conn.execute("ALTER TABLE graph_edges ADD COLUMN resolved INTEGER NOT NULL DEFAULT 1;")
        if "target_raw" not in edge_cols:
            conn.execute("ALTER TABLE graph_edges ADD COLUMN target_raw TEXT;")
        if "target_symbol_id" in edge_cols and not self._column_nullable(
            conn, "graph_edges", "target_symbol_id"
        ):
            self._rebuild_edges_nullable_target(conn)
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ai;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_ad;")
        conn.execute("DROP TRIGGER IF EXISTS chunks_fts_au;")
        conn.execute("DROP TABLE IF EXISTS chunks_fts;")
        conn.execute(CHUNKS_FTS_DDL)
        for trigger in CHUNKS_FTS_TRIGGERS:
            conn.execute(trigger)
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")

    def _migrate_v14(self, conn: sqlite3.Connection) -> None:
        """Migrate a v13 (or older) database to schema v14.

        Adds the additive graph-fidelity tables (``module_edges``,
        ``symbol_rationale`` with its FTS index, and ``doc_links``). The base
        DDL is idempotent and has already run, so this migration only rebuilds
        the rationale FTS index so an existing database starts at parity.
        """
        logger.info("Migrating schema <= v13 -> v14")
        conn.execute("INSERT INTO rationale_fts(rationale_fts) VALUES('rebuild');")

    def _migrate_v16(self, conn: sqlite3.Connection) -> None:
        """Migrate a v15 (or older) database to schema v16.

        Replaces the unique ``idx_symbols_conventional_fqn`` index with a
        non-unique one. Conventional FQNs collide legitimately: duplicate
        copies of a class in separate source roots, and a field sharing its
        name with a no-arg accessor. The unique constraint silently dropped
        those symbols, so a re-index is required to restore them.
        """
        logger.info("Migrating schema <= v15 -> v16")
        conn.execute("DROP INDEX IF EXISTS idx_symbols_conventional_fqn;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbols_conventional_fqn ON symbols(conventional_fqn);"
        )

    def _migrate_v17(self, conn: sqlite3.Connection) -> None:
        """Migrate a v16 (or older) database to schema v17.

        Collapses duplicate unresolved edges and then creates the partial
        unique index that keeps them collapsed. SQLite's table-level UNIQUE
        constraint cannot deduplicate rows whose ``target_symbol_id`` is NULL,
        so repeated external references previously inserted one row per call.
        Coverage is stored in the additive ``index_coverage`` table created by
        the base schema DDL.
        """
        logger.info("Migrating schema <= v16 -> v17")
        GraphDatabase._dedupe_unresolved_edges(conn)
        conn.execute(UNRESOLVED_EDGE_UNIQUE_INDEX)

    def _migrate_v18(self, conn: sqlite3.Connection) -> None:
        """Migrate a v17 (or older) database to schema v18.

        Adds the edge-model and trust columns: symbol ``canonical_fqn``,
        ``visibility``, ``is_test``, ``is_entry_point``, ``entry_point_reason``,
        and ``importance``; edge ``properties``; and the derived
        ``symbol_degrees`` table. ``graph_edges`` is rebuilt when its CHECK
        constraint predates the widened edge-type set, preserving every row.

        Existing symbols are backfilled so a migrated index is immediately
        queryable: ``canonical_fqn`` is derived from the recorded index root and
        ``is_test`` from the path classifier. The entry-point and importance
        passes run on the next index, which the schema bump already forces.
        """
        logger.info("Migrating schema <= v17 -> v18")
        symbol_columns = {r["name"] for r in conn.execute("PRAGMA table_info(symbols);").fetchall()}
        additions = (
            ("canonical_fqn", "TEXT"),
            ("visibility", "TEXT"),
            ("is_test", "INTEGER NOT NULL DEFAULT 0"),
            ("is_entry_point", "INTEGER NOT NULL DEFAULT 0"),
            ("entry_point_reason", "TEXT"),
            ("importance", "REAL NOT NULL DEFAULT 0"),
        )
        for column, definition in additions:
            if column not in symbol_columns:
                conn.execute(f"ALTER TABLE symbols ADD COLUMN {column} {definition};")

        if GraphDatabase._edges_need_widening(conn):
            GraphDatabase._rebuild_edges_table(conn)
        conn.execute(SYMBOL_DEGREES_TABLE_DDL)
        for index in SYMBOL_DEGREES_INDEXES:
            conn.execute(index)
        for index in SYMBOL_V18_INDEXES:
            conn.execute(index)

        root_row = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_root';"
        ).fetchone()
        index_root = Path(root_row["value"]) if root_row is not None else None
        GraphDatabase._backfill_canonical_fqns(conn, index_root)
        GraphDatabase._backfill_symbol_test_flags(conn)

    def _migrate_v19(self, conn: sqlite3.Connection) -> None:
        """Migrate a v18 (or older) database to schema v19.

        Makes the keyword index independent of the checkout location. FTS5
        length normalisation counts every token in a row, so the absolute
        ``file_path`` and the path-prefixed ``fqn`` made BM25 scores depend on
        where the repository lived. The scored index keeps only
        ``code_chunks.fqn_rel`` (repo-relative), path lookup moves to the
        separate ``paths_fts`` table, and both are rebuilt.
        """
        logger.info("Migrating schema <= v18 -> v19")
        GraphDatabase._backfill_relative_fqns(conn)
        GraphDatabase._rebuild_scored_fts(conn)

    @staticmethod
    def _backfill_relative_fqns(conn: sqlite3.Connection) -> None:
        """Populate ``fqn_rel``/``path_rel`` from the recorded index root."""
        root_row = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_root';"
        ).fetchone()
        if root_row is not None and root_row["value"]:
            root = str(root_row["value"]).rstrip("/\\")
            conn.execute(
                "UPDATE code_chunks "
                "SET fqn_rel = ltrim(substr(fqn, length(?) + 1), '/\\') "
                "WHERE substr(fqn, 1, length(?)) = ?;",
                (root, root, root),
            )
            conn.execute(
                "UPDATE code_chunks "
                "SET path_rel = ltrim(substr(file_path, length(?) + 1), '/\\') "
                "WHERE substr(file_path, 1, length(?)) = ?;",
                (root, root, root),
            )
        conn.execute("UPDATE code_chunks SET fqn_rel = fqn WHERE fqn_rel IS NULL;")
        conn.execute("UPDATE code_chunks SET path_rel = file_path WHERE path_rel IS NULL;")

    @staticmethod
    def _rebuild_scored_fts(conn: sqlite3.Connection) -> None:
        """Recreate and repopulate the keyword and path indexes."""
        for name in CHUNKS_FTS_TRIGGER_NAMES:
            conn.execute(f"DROP TRIGGER IF EXISTS {name};")
        conn.execute("DROP TABLE IF EXISTS chunks_fts;")
        conn.execute("DROP TABLE IF EXISTS paths_fts;")
        conn.execute(CHUNKS_FTS_DDL)
        conn.execute(PATHS_FTS_DDL)
        for trigger in [*CHUNKS_FTS_TRIGGERS, *PATHS_FTS_TRIGGERS]:
            conn.execute(trigger)
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")
        conn.execute(
            "INSERT INTO paths_fts(rowid, file_path) SELECT id, file_path FROM code_chunks;"
        )

    @staticmethod
    def _edges_need_widening(conn: sqlite3.Connection) -> bool:
        """Return whether ``graph_edges`` lacks properties or a widened CHECK."""
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(graph_edges);").fetchall()}
        if "properties" not in columns:
            return True
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'graph_edges';"
        ).fetchone()
        ddl = (row["sql"] or "") if row is not None else ""
        return "'IMPLEMENTS'" not in ddl

    @staticmethod
    def _rebuild_edges_table(conn: sqlite3.Connection) -> None:
        """Recreate ``graph_edges`` with the v18 column set and CHECK.

        SQLite cannot widen a CHECK constraint in place, so the table is
        rebuilt. Only columns present in the old table are copied; new columns
        take their defaults. Indexes are recreated after the old table is
        dropped so their names are free.
        """
        old_columns = {
            r["name"] for r in conn.execute("PRAGMA table_info(graph_edges);").fetchall()
        }
        conn.execute("ALTER TABLE graph_edges RENAME TO graph_edges_old;")
        conn.execute(GRAPH_EDGES_TABLE_DDL)
        copy_columns = [
            column
            for column in (
                "id",
                "source_symbol_id",
                "target_symbol_id",
                "edge_type",
                "source_range",
                "target_range",
                "resolution_tier",
                "resolved",
                "target_raw",
                "properties",
                "created_at",
            )
            if column in old_columns
        ]
        column_list = ", ".join(copy_columns)
        conn.execute(
            f"INSERT INTO graph_edges ({column_list}) SELECT {column_list} FROM graph_edges_old;"
        )
        conn.execute("DROP TABLE graph_edges_old;")
        for index in GRAPH_EDGES_INDEXES:
            conn.execute(index)
        conn.execute(UNRESOLVED_EDGE_UNIQUE_INDEX)

    @staticmethod
    def _backfill_canonical_fqns(conn: sqlite3.Connection, index_root: Path | None) -> None:
        """Populate ``symbols.canonical_fqn`` from the recorded index root."""
        rows = conn.execute(
            "SELECT id, fqn, file_path FROM symbols WHERE canonical_fqn IS NULL;"
        ).fetchall()
        if not rows:
            return
        updates: list[tuple[str, int]] = []
        for row in rows:
            file_path = str(row["file_path"] or "")
            fqn = str(row["fqn"] or "")
            relative = file_path
            if index_root is not None:
                try:
                    relative = (
                        Path(file_path).resolve().relative_to(index_root.resolve()).as_posix()
                    )
                except (ValueError, OSError):
                    relative = Path(file_path).as_posix()
            canonical = f"{relative}{fqn[len(file_path) :]}" if fqn.startswith(file_path) else fqn
            updates.append((canonical, int(row["id"])))
        conn.executemany("UPDATE symbols SET canonical_fqn = ? WHERE id = ?;", updates)

    @staticmethod
    def _backfill_symbol_test_flags(conn: sqlite3.Connection) -> None:
        """Populate ``symbols.is_test`` from the shared path classifier."""
        from code_search.engine.config import _is_test_file

        rows = conn.execute("SELECT DISTINCT file_path FROM symbols;").fetchall()
        updates = [
            (1 if _is_test_file(str(row["file_path"] or "")) else 0, row["file_path"])
            for row in rows
        ]
        conn.executemany("UPDATE symbols SET is_test = ? WHERE file_path = ?;", updates)

    @staticmethod
    def _unresolved_edge_index_exists(conn: sqlite3.Connection) -> bool:
        """Return whether the unresolved-edge partial unique index exists."""
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_edges_unique_unresolved';"
        ).fetchone()
        return row is not None

    @staticmethod
    def _dedupe_unresolved_edges(conn: sqlite3.Connection) -> None:
        """Keep the oldest row per unresolved ``(source, type, raw)`` tuple.

        Only rows with ``target_symbol_id IS NULL`` are touched; resolved edges
        are left alone even when their raw text is identical.
        """
        conn.execute(
            "DELETE FROM graph_edges "
            "WHERE target_symbol_id IS NULL AND id NOT IN ("
            "  SELECT MIN(id) FROM graph_edges "
            "  WHERE target_symbol_id IS NULL "
            "  GROUP BY source_symbol_id, edge_type, COALESCE(target_raw, '')"
            ");"
        )

    def _ensure_unresolved_edge_index(self, conn: sqlite3.Connection) -> None:
        """Create the unresolved-edge partial unique index when it is missing.

        Runs on every :meth:`initialize` because an index can be absent on a
        database whose version already claims v17 (for example one opened by an
        older build during a rolling upgrade). Deduplication precedes creation
        so an existing index-less database migrates cleanly.
        """
        if self._unresolved_edge_index_exists(conn):
            return
        self._dedupe_unresolved_edges(conn)
        conn.execute(UNRESOLVED_EDGE_UNIQUE_INDEX)

    @staticmethod
    def _ensure_v18_indexes(conn: sqlite3.Connection) -> None:
        """Create v18 column indexes on every open, not only after a migration.

        The base DDL cannot create them for an older database (the columns do
        not exist yet), and a fresh database never runs the migration, so this
        idempotent check closes both paths.
        """
        for index in SYMBOL_V18_INDEXES:
            conn.execute(index)

    @staticmethod
    def _column_nullable(conn: sqlite3.Connection, table: str, column: str) -> bool:
        """Return whether *column* on *table* is nullable."""
        row = conn.execute(f"PRAGMA table_info({table});").fetchall()
        for r in row:
            if r["name"] == column:
                return bool(r["notnull"]) is False
        return True

    @staticmethod
    def _rebuild_edges_nullable_target(conn: sqlite3.Connection) -> None:
        """Recreate ``graph_edges`` with a nullable ``target_symbol_id``.

        SQLite cannot ALTER a column's nullability, so the table is rebuilt
        preserving existing rows (including the new columns, when present) and
        re-creating its indexes. Called during the v12 migration when an older
        ``NOT NULL`` constraint is detected.
        """
        conn.execute("ALTER TABLE graph_edges RENAME TO graph_edges_old;")
        conn.execute(GRAPH_EDGES_TABLE_DDL)
        edge_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(graph_edges_old);").fetchall()
        }
        columns = (
            "id, source_symbol_id, target_symbol_id, edge_type, source_range, "
            "target_range, resolution_tier"
        )
        select_cols = columns
        if "resolved" in edge_cols:
            columns += ", resolved"
            select_cols += ", resolved"
        if "target_raw" in edge_cols:
            columns += ", target_raw"
            select_cols += ", target_raw"
        if "created_at" in edge_cols:
            columns += ", created_at"
            select_cols += ", created_at"
        conn.execute(
            f"INSERT INTO graph_edges ({columns}) SELECT {select_cols} FROM graph_edges_old;"
        )
        conn.execute("DROP TABLE graph_edges_old;")
        for index in GRAPH_EDGES_INDEXES:
            conn.execute(index)

    def _migrate_v10(self, conn: sqlite3.Connection) -> None:
        """Migrate a v10 (or older) database to the v11 schema.

        Adds the ``parse_failed`` flag column to ``file_checksums`` so the
        enumerate mode can report files the structural layer could not parse
        (``excluded``/``complete: false``). Existing rows keep the default
        ``0`` and are self-healed on the next re-index. No FTS rebuild needed.
        """
        logger.info("Migrating schema <= v10 -> v11")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(file_checksums);").fetchall()}
        if "parse_failed" not in cols:
            conn.execute(
                "ALTER TABLE file_checksums ADD COLUMN parse_failed INTEGER NOT NULL DEFAULT 0;"
            )

    @staticmethod
    def _drop_edges_self_check(conn: sqlite3.Connection) -> None:
        """Rebuild ``graph_edges`` without the ``source != target`` CHECK.

        The v6 DDL enforced ``CHECK(source_symbol_id != target_symbol_id)``,
        which silently blocks genuine recursive self-call edges. Schema v7
        guards self-edges at the application layer instead (the batch guard and
        the post-index validation sweep), so the constraint is removed by
        recreating the table and preserving existing rows.
        """
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'graph_edges';"
        ).fetchone()
        if row is None:
            return
        ddl = row["sql"] or ""
        if "source_symbol_id != target_symbol_id" not in ddl:
            return
        conn.execute("ALTER TABLE graph_edges RENAME TO graph_edges_old;")
        conn.execute(GRAPH_EDGES_TABLE_DDL)
        conn.execute(
            "INSERT INTO graph_edges "
            "(id, source_symbol_id, target_symbol_id, edge_type, source_range, "
            "target_range, resolution_tier, created_at) "
            "SELECT id, source_symbol_id, target_symbol_id, edge_type, source_range, "
            "target_range, resolution_tier, created_at FROM graph_edges_old;"
        )
        conn.execute("DROP TABLE graph_edges_old;")
        for index in GRAPH_EDGES_INDEXES:
            conn.execute(index)

    def rebuild_fts(self) -> int:
        """Clear and repopulate the keyword and path indexes from ``code_chunks``.

        Uses the FTS5 ``rebuild`` command for the external-content keyword
        index and repopulates ``paths_fts`` from the same rows, then returns
        the keyword row count so callers can verify
        ``COUNT(code_chunks) == COUNT(chunks_fts)`` parity.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")
                conn.execute("DELETE FROM paths_fts;")
                conn.execute(
                    "INSERT INTO paths_fts(rowid, file_path) SELECT id, file_path FROM code_chunks;"
                )
                conn.commit()
                row = conn.execute("SELECT COUNT(*) AS cnt FROM chunks_fts;").fetchone()
                count = int(row["cnt"]) if row else 0
                return count
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
                self._local.conn = None

    def run_post_index_maintenance(self, *, full_rebuild: bool) -> None:
        """Compact SQLite storage after a build completes.

        Merges the FTS5 segments (``optimize``), refreshes planner statistics
        (``ANALYZE``), and truncates the WAL so it cannot keep growing while
        long-lived readers hold snapshots. ``VACUUM`` runs only after a full
        rebuild; an incremental run adds little free space, so paying the
        rewrite cost every time is not worthwhile.

        Failures are logged rather than raised: the index is already committed
        and usable, and maintenance is a best-effort storage optimisation.

        Args:
            full_rebuild: Whether this build replaced the whole corpus.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize');")
                conn.execute("INSERT INTO paths_fts(paths_fts) VALUES('optimize');")
                conn.execute("ANALYZE;")
                conn.commit()
                if full_rebuild:
                    conn.execute("VACUUM;")
                row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                if row is not None and int(row["busy"]) != 0:
                    logger.warning("WAL checkpoint left readers active: %s", tuple(row))
            except Exception:
                logger.warning("Post-index maintenance failed", exc_info=True)
            finally:
                conn.close()
                self._local.conn = None

    def fts_count(self) -> int:
        """Return the number of rows currently in ``chunks_fts``."""
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM chunks_fts;").fetchone()
            return int(row["cnt"]) if row else 0

    def close(self) -> None:
        """Close the calling thread's cached connection, if any."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None


class EdgeStore:
    """High-level CRUD for call-graph edges and traversal queries."""

    def __init__(self, db: GraphDatabase, settings: Settings | None = None) -> None:
        """Initialize the edge store over a graph database.

        Args:
            db: The :class:`GraphDatabase` whose ``graph_edges`` table backs
                this store.
            settings: Engine settings; defaults to ``Settings.from_env()``.
        """
        self._db = db
        self._settings = settings or Settings.from_env()

    def insert_edge(
        self,
        source_symbol_id: int,
        target_symbol_id: int,
        edge_type: str,
        source_range: str | None = None,
        target_range: str | None = None,
        resolution_tier: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> int | None:
        """Insert a single directed edge between two symbols.

        Validates *edge_type* against :data:`GRAPH_EDGE_TYPES` and skips
        self-loops (``source == target``), which are not representable per the
        schema design.

        Args:
            source_symbol_id: The caller/referencing symbol id.
            target_symbol_id: The callee/referenced symbol id.
            edge_type: One of the valid edge kinds.
            source_range: JSON ``[s_line, s_col, e_line, e_col]`` call range.
            target_range: JSON target range, when known.
            resolution_tier: Confidence tier (e.g. ``exact``, ``fallback``).
            properties: Optional JSON-serialisable evidence for the edge.

        Returns:
            The new row id, or ``None`` when the edge is skipped or the
            insert fails.
        """
        if edge_type not in GRAPH_EDGE_TYPES:
            logger.warning("Invalid edge type: %s", edge_type)
            return None
        if source_symbol_id == target_symbol_id:
            logger.debug("Skipping self-loop edge")
            return None
        with self._db.write_transaction() as conn:
            try:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO graph_edges "
                    "(source_symbol_id, target_symbol_id, edge_type, source_range, "
                    "target_range, resolution_tier, properties) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?);",
                    (
                        source_symbol_id,
                        target_symbol_id,
                        edge_type,
                        source_range,
                        target_range,
                        resolution_tier,
                        json.dumps(properties or {}),
                    ),
                )
                return cursor.lastrowid
            except Exception as exc:
                logger.warning("Failed to insert edge: %s", exc)
                return None

    def insert_edges_batch(
        self, edges: list[dict[str, Any]], conn: sqlite3.Connection | None = None
    ) -> None:
        """Insert many edges at once, guarding against spurious self-edges.

        Mirrors ``insert_edge``'s ``source == target`` guard: a
        ``source_symbol_id == target_symbol_id`` edge is a spurious
        self-resolution (same-name look-alike) and is skipped unless the
        caller explicitly marks it as a genuine recursive self-call
        (``recursive=True``).

        Args:
            edges: Edge dicts to insert.
            conn: An existing writer connection to reuse (no commit is issued);
                when ``None`` a fresh transaction is opened and committed.
        """
        if conn is not None:
            self._insert_edges_rows(conn, edges)
            return
        with self._db.write_transaction() as owned:
            self._insert_edges_rows(owned, edges)

    @staticmethod
    def _insert_edges_rows(conn: sqlite3.Connection, edges: list[dict[str, Any]]) -> None:
        """Insert *edges* over *conn*, skipping spurious self-edges per row."""
        for edge in edges:
            try:
                src_id = edge["source_symbol_id"]
                tgt_id = edge["target_symbol_id"]
                if src_id == tgt_id and not edge.get("recursive", False):
                    logger.debug(
                        "Skipping spurious self-edge batch (%s -> %s)",
                        src_id,
                        tgt_id,
                    )
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO graph_edges "
                    "(source_symbol_id, target_symbol_id, "
                    "edge_type, source_range, target_range, resolution_tier, "
                    "resolved, target_raw, properties) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        src_id,
                        tgt_id,
                        edge["edge_type"],
                        edge.get("source_range"),
                        edge.get("target_range"),
                        edge.get("resolution_tier"),
                        0 if edge.get("resolved") == 0 else 1,
                        edge.get("target_raw"),
                        _edge_properties_json(edge.get("properties")),
                    ),
                )
            except Exception as exc:
                logger.warning("Failed to insert edge %s: %s", edge.get("edge_type"), exc)

    @staticmethod
    def _edge_call_line(source_range: str | None) -> int | None:
        """Extract the start line from a ``[s_line,s_col,e_line,e_col]`` JSON range."""
        if not source_range:
            return None
        try:
            import json as _json

            parts = _json.loads(source_range)
            if isinstance(parts, list) and parts:
                return int(parts[0])
        except Exception:
            return None
        return None

    def run_edge_validation_sweep(self) -> dict[str, int]:
        """Post-index edge validation sweep.

        Deletes edges that are signatures of mis-resolution:
          1. id-self-edges that are NOT genuine recursive self-calls — a
             recursive self-call has its ``source_range`` (call location)
             inside the symbol's own declaration range; otherwise the edge is
             a spurious same-name look-alike and is dropped;
          2. edges whose ``source_range`` call line falls outside the caller
             symbol's declaration range (out-of-range attachment);
          3. same-name-different-id pairs within the same file (mis-resolution
             signature such as ``save -> save`` / ``isAuthenticated ->
             isAuthenticated``), keeping genuine cross-file same-name calls
             (e.g. ``AuthController.authenticate -> AuthService.authenticate``);
          4. ``range``/``fallback``-tier attachments when a higher-confidence
             edge to a same-named symbol already exists from the same source.

        Returns a summary dict ``{deleted, kept_recursive}``.
        """
        deleted = 0
        kept_recursive = 0
        with self._db.write_transaction() as conn:
            # --- 1. id-self-edges that are not genuine recursive self-calls ---
            self_rows = conn.execute(
                "SELECT e.id, e.source_symbol_id, e.source_range, "
                "s.line_start, s.line_end "
                "FROM graph_edges e JOIN symbols s ON e.source_symbol_id = s.id "
                "WHERE e.source_symbol_id = e.target_symbol_id;"
            ).fetchall()
            for row in self_rows:
                call_line = self._edge_call_line(row["source_range"])
                recursive = (
                    call_line is not None
                    and row["line_start"] is not None
                    and row["line_end"] is not None
                    and row["line_start"] <= call_line <= row["line_end"]
                )
                if recursive:
                    kept_recursive += 1
                    continue
                conn.execute("DELETE FROM graph_edges WHERE id = ?;", (row["id"],))
                deleted += 1

            # --- 2. edges whose call line falls outside the caller's range ---
            out_rows = conn.execute(
                "SELECT e.id, e.source_range, s.line_start, s.line_end "
                "FROM graph_edges e JOIN symbols s ON e.source_symbol_id = s.id "
                "WHERE e.source_range IS NOT NULL "
                "AND s.line_start IS NOT NULL AND s.line_end IS NOT NULL;"
            ).fetchall()
            for row in out_rows:
                call_line = self._edge_call_line(row["source_range"])
                if call_line is None:
                    continue
                if not (row["line_start"] <= call_line <= row["line_end"]):
                    conn.execute("DELETE FROM graph_edges WHERE id = ?;", (row["id"],))
                    deleted += 1

            # --- 3. same-name-different-id pairs in the same file ---
            same_name = conn.execute(
                "SELECT e.id FROM graph_edges e "
                "JOIN symbols s1 ON e.source_symbol_id = s1.id "
                "JOIN symbols s2 ON e.target_symbol_id = s2.id "
                "WHERE s1.name = s2.name "
                "AND e.source_symbol_id != e.target_symbol_id "
                "AND s1.file_path = s2.file_path;"
            ).fetchall()
            for row in same_name:
                conn.execute("DELETE FROM graph_edges WHERE id = ?;", (row["id"],))
                deleted += 1

            # --- 4. prefer higher-confidence tier attachments ---
            low_tier = conn.execute(
                "SELECT e.id, e.source_symbol_id, s2.name, e.resolution_tier "
                "FROM graph_edges e JOIN symbols s2 ON e.target_symbol_id = s2.id "
                "WHERE e.resolution_tier IN ('range', 'fallback');"
            ).fetchall()
            for row in low_tier:
                better = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM graph_edges e2 "
                    "JOIN symbols s3 ON e2.target_symbol_id = s3.id "
                    "WHERE e2.source_symbol_id = ? AND s3.name = ? "
                    "AND e2.id != ? "
                    "AND e2.resolution_tier IN ('exact', 'conventional', 'same_file')"
                    " AND e2.resolution_tier IS NOT NULL;",
                    (row["source_symbol_id"], row["name"], row["id"]),
                ).fetchone()
                if better and better["cnt"]:
                    conn.execute("DELETE FROM graph_edges WHERE id = ?;", (row["id"],))
                    deleted += 1

        return {"deleted": deleted, "kept_recursive": kept_recursive}

    def resolve_symbol_definition(
        self, fqn: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Resolve *fqn* to ``(symbol, candidates)`` with source code populated.

        Delegates to the shared ``SymbolStore.resolve_name`` envelope so the
        CLI ``symbol`` command and the MCP definition tool cannot diverge,
        while keeping this store's ``code_chunks``-backed
        ``source_code`` population. Accepts full file-path FQNs, conventional
        FQNs, partial / suffix names, and dotted ``Class.method`` queries.
        Ambiguous partial names yield an empty symbol and a ``candidates``
        disambiguation list. Near-miss names (edit-distance fallback)
        yield candidates annotated with ``edit_distance`` and
        ``suggestion: true`` instead of a silent empty list.
        """
        from code_search.engine.symbols import SymbolStore

        envelope = SymbolStore(self._db, self._settings).resolve_name(fqn)
        symbol = envelope["symbol"]
        if symbol is not None:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT content FROM code_chunks WHERE fqn = ? AND is_definition = 1 LIMIT 1;",
                    (symbol.get("fqn"),),
                ).fetchone()
                symbol["source_code"] = (
                    row["content"]
                    if row and row["content"]
                    else read_source_slice(
                        symbol.get("file_path", ""),
                        symbol.get("line_start"),
                        symbol.get("line_end"),
                    )
                )
        return symbol, envelope["candidates"]

    def get_symbol_definition(self, fqn: str) -> dict[str, Any] | None:
        """Look up a symbol by FQN, returning its definition + source code + parent info."""
        symbol, _candidates = self.resolve_symbol_definition(fqn)
        return symbol

    def get_call_graph(
        self,
        symbol_id: int,
        direction: str = "both",
        max_depth: int = 1,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, list[dict[str, Any]]]:
        """Traverse callers and/or callees via recursive CTE, clipped to *max_depth*.

        Args:
            symbol_id: The root symbol id.
            direction: ``both``, ``callers``, or ``callees``.
            max_depth: Maximum traversal depth (clipped to 5).
            limit: Optional per-direction row cap; ``None`` returns every row.
            offset: Zero-based row offset applied to each direction.
        """
        result: dict[str, list[dict[str, Any]]] = {"callers": [], "callees": []}
        clipped_depth = min(max_depth, 5)

        with self._db.connect() as conn:
            if direction in ("both", "callers"):
                rows, _total = self._traverse_callers(
                    conn, symbol_id, clipped_depth, limit=limit, offset=offset
                )
                result["callers"] = rows

            if direction in ("both", "callees"):
                rows, _total = self._traverse_callees(
                    conn, symbol_id, clipped_depth, limit=limit, offset=offset
                )
                result["callees"] = rows

        return result

    def get_call_graph_page(
        self,
        symbol_id: int,
        direction: str = "both",
        max_depth: int = 1,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return a bounded page of the call graph plus exact per-direction totals.

        The page size applies to each populated direction, so ``callers`` and
        ``callees`` always start at the same ``offset`` and stay independently
        paginable. Totals are computed by the same recursive CTE before the
        row cap, not by a second traversal.

        Args:
            symbol_id: The root symbol id.
            direction: ``both``, ``callers``, or ``callees``.
            max_depth: Maximum traversal depth (clipped to 5).
            limit: Maximum rows returned per direction (at least 1).
            offset: Zero-based row offset applied to each direction.

        Returns:
            ``{"callers", "callees", "paging"}`` where ``paging`` carries the
            cap, offset, and ``returned``/``total``/``has_more``/``next_offset``
            for each direction.
        """
        clipped_depth = min(max_depth, 5)
        page_size = max(1, int(limit))
        start = max(0, int(offset))
        result: dict[str, Any] = {"callers": [], "callees": [], "paging": {}}

        with self._db.connect() as conn:
            if direction in ("both", "callers"):
                callers, caller_total = self._traverse_callers(
                    conn, symbol_id, clipped_depth, limit=page_size, offset=start
                )
                result["callers"] = callers
                result["paging"]["callers"] = _call_graph_page(
                    len(callers), caller_total, page_size, start
                )
            if direction in ("both", "callees"):
                callees, callee_total = self._traverse_callees(
                    conn, symbol_id, clipped_depth, limit=page_size, offset=start
                )
                result["callees"] = callees
                result["paging"]["callees"] = _call_graph_page(
                    len(callees), callee_total, page_size, start
                )

        return result

    def _traverse_callers(
        self,
        conn: sqlite3.Connection,
        symbol_id: int,
        max_depth: int,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return symbols that transitively call *symbol_id*, with minimum depth.

        Uses a recursive CTE that walks ``CALLS`` edges backwards from the
        target, pruning at *max_depth* and breaking cycles via an ancestor
        path guard.

        The CTE enumerates every simple path within the bound, so a caller
        reachable at several depths would otherwise repeat once per depth.
        A window rank keeps only the shallowest row per caller symbol id,
        breaking equal-depth ties by the lexicographically smallest call-site
        range so the retained row (and its ``source_range``) is deterministic.

        Args:
            conn: The database connection to query against.
            symbol_id: The callee symbol id to find callers of.
            max_depth: Maximum traversal depth (already clipped).

        Returns:
            ``(rows, total)`` where rows are deduplicated caller rows
            ``{fqn, kind, file_path, line_start, source_range, depth}`` ordered
            by depth, then FQN, then symbol id. ``total`` is the exact count
            before *limit*/*offset*.
        """
        page_clause = "" if limit is None else " LIMIT ? OFFSET ?"
        params: list[Any] = [symbol_id, max_depth]
        if limit is not None:
            params.extend([max(0, int(limit)), max(0, int(offset))])
        rows = conn.execute(
            "WITH RECURSIVE callers AS ( "
            "SELECT e.source_symbol_id AS caller_id, e.source_range, 1 AS depth, "
            "'|' || e.source_symbol_id || '|' AS path "
            "FROM graph_edges e "
            "WHERE e.target_symbol_id = ? AND e.edge_type = 'CALLS' "
            "UNION ALL "
            "SELECT e.source_symbol_id, e.source_range, c.depth + 1, "
            "c.path || e.source_symbol_id || '|' "
            "FROM graph_edges e "
            "JOIN callers c ON e.target_symbol_id = c.caller_id "
            "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
            "AND instr(c.path, '|' || e.source_symbol_id || '|') = 0 "
            ") "
            "SELECT s.fqn, s.kind, s.file_path, s.line_start, "
            "ranked.source_range, ranked.depth, "
            "COUNT(*) OVER () AS total_count "
            "FROM ( "
            "SELECT c.caller_id, c.source_range, c.depth, "
            "ROW_NUMBER() OVER ( "
            "PARTITION BY c.caller_id ORDER BY c.depth, c.source_range "
            ") AS rn "
            "FROM callers c "
            ") ranked "
            "JOIN symbols s ON ranked.caller_id = s.id "
            "WHERE ranked.rn = 1 "
            "ORDER BY ranked.depth, s.fqn, ranked.caller_id" + page_clause + ";",
            params,
        ).fetchall()
        total = int(rows[0]["total_count"]) if rows else 0
        shaped = []
        for row in rows:
            item = dict(row)
            item.pop("total_count", None)
            shaped.append(item)
        return (
            self._attach_edge_signature(conn, symbol_id, shaped, is_callee_traversal=False),
            total,
        )

    def _attach_edge_signature(
        self,
        conn: sqlite3.Connection,
        symbol_id: int,
        rows: list[dict[str, Any]],
        is_callee_traversal: bool = False,
    ) -> list[dict[str, Any]]:
        """Augment traversal rows with the callee signature + overload set.

        Each returned edge describes (a) the ``target_signature`` the callee
        symbol actually targets and (b) the ``overloads`` list — every
        signature available on the callee's enclosing type — so consumers can
        see which overload a call site hits. On caller edges the root
        symbol *is* the target, so the root's signature/overloads are correct;
        on callee edges each resolved callee's ``target_signature`` is derived
        from the callee's own symbol row and its
        own overload set stays visible. Unresolved edges keep
        ``target_signature: null``. Skipped when the root symbol row is
        missing.
        """
        if not rows:
            return rows
        root = conn.execute(
            "SELECT fqn, conventional_fqn, name, parent_symbol_id FROM symbols WHERE id = ?;",
            (symbol_id,),
        ).fetchone()
        if root is None:
            return rows
        root_signature = _signature_from_fqn(root["conventional_fqn"] or root["fqn"])
        root_overloads: list[dict[str, Any]] = []
        try:
            o_rows = conn.execute(
                "SELECT fqn, conventional_fqn FROM symbols "
                "WHERE name = ? AND parent_symbol_id IS ?;",
                (root["name"], root["parent_symbol_id"]),
            ).fetchall()
            for o in o_rows:
                sig = _signature_from_fqn(o["conventional_fqn"] or o["fqn"])
                if sig is not None:
                    root_overloads.append(sig)
        except Exception:
            pass
        if not is_callee_traversal:
            for r in rows:
                if r.get("resolved") is False:
                    r["target_signature"] = None
                    r["overloads"] = []
                    continue
                r["target_signature"] = root_signature
                r["overloads"] = root_overloads
            return rows
        for r in rows:
            if r.get("resolved") is False:
                r["target_signature"] = None
                r["overloads"] = []
                continue
            callee = conn.execute(
                "SELECT fqn, conventional_fqn, name, parent_symbol_id FROM symbols WHERE id = ?;",
                (r.get("callee_id"),),
            ).fetchone()
            if callee is None:
                r["target_signature"] = None
                r["overloads"] = []
                continue
            r["target_signature"] = _signature_from_fqn(callee["conventional_fqn"] or callee["fqn"])
            r["overloads"] = self._overloads_for(conn, callee)
        return rows

    @staticmethod
    def _overloads_for(conn: sqlite3.Connection, symbol_row: Any) -> list[dict[str, Any]]:
        """Return the overload-signature list for *symbol_row*'s name/parent."""
        overloads: list[dict[str, Any]] = []
        try:
            o_rows = conn.execute(
                "SELECT fqn, conventional_fqn FROM symbols "
                "WHERE name = ? AND parent_symbol_id IS ?;",
                (symbol_row["name"], symbol_row["parent_symbol_id"]),
            ).fetchall()
            for o in o_rows:
                sig = _signature_from_fqn(o["conventional_fqn"] or o["fqn"])
                if sig is not None:
                    overloads.append(sig)
        except Exception:
            pass
        return overloads

    def _traverse_callees(
        self,
        conn: sqlite3.Connection,
        symbol_id: int,
        max_depth: int,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return symbols that *symbol_id* transitively calls, with minimum depth.

        The forward mirror of :meth:`_traverse_callers`: a recursive CTE walks
        ``CALLS`` edges from the source, pruning at *max_depth* and breaking
        cycles via an ancestor path guard.

        A callee is identified by its resolved symbol id, or — when the edge
        is unresolved — by its raw target reference, so identical external
        references collapse while distinct ones stay separate. A window rank
        keeps only the shallowest row per identity, breaking equal-depth ties
        by the smallest target range and then the callee id, so the retained
        row (and its ``target_range``) is deterministic.

        Args:
            conn: The database connection to query against.
            symbol_id: The caller symbol id to find callees of.
            max_depth: Maximum traversal depth (already clipped).

        Returns:
            ``(rows, total)`` where rows are deduplicated callee rows
            ``{fqn, conventional_fqn, kind, file_path, line_start, callee_id,
            target_range, depth, resolved, target_raw}`` ordered by depth, then
            FQN (falling back to the raw target), then symbol id. ``total`` is
            the exact count before *limit*/*offset*.
        """
        page_clause = "" if limit is None else " LIMIT ? OFFSET ?"
        params: list[Any] = [symbol_id, max_depth]
        if limit is not None:
            params.extend([max(0, int(limit)), max(0, int(offset))])
        rows = conn.execute(
            "WITH RECURSIVE callees AS ( "
            "SELECT e.target_symbol_id AS callee_id, e.target_range, "
            "e.resolved AS resolved, e.target_raw AS target_raw, 1 AS depth, "
            "'|' || COALESCE(e.target_symbol_id, 'u') || '|' AS path "
            "FROM graph_edges e "
            "WHERE e.source_symbol_id = ? AND e.edge_type = 'CALLS' "
            "UNION ALL "
            "SELECT e.target_symbol_id, e.target_range, e.resolved, e.target_raw, "
            "c.depth + 1, c.path || COALESCE(e.target_symbol_id, 'u') || '|' "
            "FROM graph_edges e "
            "JOIN callees c ON e.source_symbol_id = c.callee_id "
            "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
            "AND instr(c.path, '|' || COALESCE(e.target_symbol_id, 'u') || '|') = 0 "
            ") "
            "SELECT s.fqn, s.conventional_fqn, s.kind, s.file_path, s.line_start, "
            "ranked.callee_id, ranked.target_range, ranked.depth, "
            "ranked.resolved, ranked.target_raw, "
            "COUNT(*) OVER () AS total_count "
            "FROM ( "
            "SELECT c.callee_id, c.target_range, c.depth, c.resolved, c.target_raw, "
            "ROW_NUMBER() OVER ( "
            "PARTITION BY CASE "
            "WHEN c.resolved = 1 AND c.callee_id IS NOT NULL "
            "THEN 's:' || c.callee_id ELSE 'u:' || COALESCE(c.target_raw, '') END "
            "ORDER BY c.depth, c.target_range, c.callee_id "
            ") AS rn "
            "FROM callees c "
            ") ranked "
            "LEFT JOIN symbols s ON ranked.callee_id = s.id "
            "WHERE ranked.rn = 1 "
            "ORDER BY ranked.depth, COALESCE(s.fqn, ranked.target_raw), ranked.callee_id"
            + page_clause
            + ";",
            params,
        ).fetchall()
        total = int(rows[0]["total_count"]) if rows else 0
        shaped: list[dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            row.pop("total_count", None)
            unresolved = row.get("resolved") == 0 or row.get("fqn") is None
            row["resolved"] = not unresolved
            row["target_raw"] = row.get("target_raw") if unresolved else None
            if unresolved:
                row["fqn"] = row.get("target_raw") or "<unresolved callee>"
                row["kind"] = "external"
                row["file_path"] = None
                row["line_start"] = None
            shaped.append(row)
        return (
            self._attach_edge_signature(conn, symbol_id, shaped, is_callee_traversal=True),
            total,
        )

    def get_subtypes(self, symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]:
        """Return types that inherit from or implement *symbol_id*, by depth.

        Walks ``INHERITS`` and ``IMPLEMENTS`` edges **backwards** (base ->
        subtype) with a recursive CTE: the seed matches
        ``target_symbol_id = symbol_id`` and each recursion follows
        ``target_symbol_id = previous source``. Traversing both types means a
        Phase 2 index uses ``IMPLEMENTS`` directly while a pre-Phase 2 index
        (where every base edge is ``INHERITS``) keeps working unchanged. The
        walk is bounded by *max_depth* and terminated on cycles by an ancestor
        path guard, so a self-inheriting or mutually-recursive hierarchy cannot
        loop.

        A subtype reachable at several depths is returned once, at its
        shallowest depth, breaking equal-depth ties by the ancestor FQN path
        then the symbol id, so the retained row (and its ``path``) is
        deterministic.

        Args:
            symbol_id: The base type whose subtypes are requested.
            max_depth: Maximum inheritance hops (default 5, matching
                ``Settings.max_graph_depth``).

        Returns:
            Subtype rows ``{id, fqn, name, kind, file_path, line_start,
            line_end, language, depth, path, relationship}`` ordered by depth,
            then kind, then FQN, then id. ``depth`` is 1 for a direct subtype
            and greater than 1 for an indirect one; ``path`` is the FQN chain
            from the queried base to the subtype; ``relationship`` is the
            direct edge type (``IMPLEMENTS`` or ``INHERITS``).
        """
        root = self._db
        with root.connect() as conn:
            root_row = conn.execute(
                "SELECT fqn FROM symbols WHERE id = ?;", (symbol_id,)
            ).fetchone()
            if root_row is None:
                return []
            root_fqn = root_row["fqn"]
            rows = conn.execute(
                "WITH RECURSIVE subtypes AS ( "
                "SELECT e.source_symbol_id AS sid, 1 AS depth, "
                "e.edge_type AS relation, "
                "'|' || e.source_symbol_id || '|' AS cpath, "
                "s.fqn AS fqn_path "
                "FROM graph_edges e INDEXED BY idx_edges_target_type "
                "JOIN symbols s ON s.id = e.source_symbol_id "
                "WHERE e.target_symbol_id = ? "
                "AND e.edge_type IN ('INHERITS', 'IMPLEMENTS') "
                "UNION ALL "
                "SELECT e.source_symbol_id, st.depth + 1, st.relation, "
                "st.cpath || e.source_symbol_id || '|', "
                "st.fqn_path || '>' || s.fqn "
                "FROM graph_edges e INDEXED BY idx_edges_target_type "
                "JOIN subtypes st ON e.target_symbol_id = st.sid "
                "JOIN symbols s ON s.id = e.source_symbol_id "
                "WHERE e.edge_type IN ('INHERITS', 'IMPLEMENTS') AND st.depth < ? "
                "AND instr(st.cpath, '|' || e.source_symbol_id || '|') = 0 "
                ") "
                "SELECT s.id, s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                "s.line_end, s.language, ranked.depth, ranked.relation, ranked.fqn_path "
                "FROM ( "
                "SELECT st.sid, st.depth, st.relation, st.fqn_path, "
                "ROW_NUMBER() OVER ( "
                "PARTITION BY st.sid ORDER BY st.depth, st.fqn_path, st.sid "
                ") AS rn "
                "FROM subtypes st "
                ") ranked "
                "JOIN symbols s ON ranked.sid = s.id "
                "WHERE ranked.rn = 1 "
                "ORDER BY ranked.depth, s.kind, s.fqn, s.id;",
                (symbol_id, max_depth),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "fqn": r["fqn"],
                "name": r["name"],
                "kind": r["kind"],
                "file_path": r["file_path"],
                "line_start": r["line_start"],
                "line_end": r["line_end"],
                "language": r["language"],
                "depth": r["depth"],
                "relationship": r["relation"],
                "path": [root_fqn, *str(r["fqn_path"]).split(">")],
            }
            for r in rows
        ]

    def get_ancestors(self, symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]:
        """Return the class ancestors of *symbol_id*, nearest base first.

        Walks ``INHERITS`` edges **forwards** (subtype -> base) with a recursive
        CTE, bounded by *max_depth* and cycle-guarded by an ancestor path.
        Only ancestors whose symbol ``kind`` is ``class`` are returned, so an
        interface a class implements is never mistaken for a concrete
        implementation site; ``depth`` 1 is the immediate base class.

        Args:
            symbol_id: The subtype whose class ancestors are requested.
            max_depth: Maximum inheritance hops (default 5).

        Returns:
            Ancestor rows ``{id, fqn, name, kind, file_path, line_start,
            line_end, language, depth}`` ordered by depth, then FQN, then id.
        """
        with self._db.connect() as conn:
            rows = conn.execute(
                "WITH RECURSIVE ancestors AS ( "
                "SELECT e.target_symbol_id AS aid, 1 AS depth, "
                "'|' || e.target_symbol_id || '|' AS cpath "
                "FROM graph_edges e INDEXED BY idx_edges_source_type "
                "WHERE e.source_symbol_id = ? AND e.edge_type = 'INHERITS' "
                "AND e.target_symbol_id IS NOT NULL "
                "UNION ALL "
                "SELECT e.target_symbol_id, a.depth + 1, "
                "a.cpath || e.target_symbol_id || '|' "
                "FROM graph_edges e INDEXED BY idx_edges_source_type "
                "JOIN ancestors a ON e.source_symbol_id = a.aid "
                "WHERE e.edge_type = 'INHERITS' AND a.depth < ? "
                "AND e.target_symbol_id IS NOT NULL "
                "AND instr(a.cpath, '|' || e.target_symbol_id || '|') = 0 "
                ") "
                "SELECT s.id, s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                "s.line_end, s.language, ranked.depth "
                "FROM ( "
                "SELECT a.aid, a.depth, "
                "ROW_NUMBER() OVER ( "
                "PARTITION BY a.aid ORDER BY a.depth, a.aid "
                ") AS rn "
                "FROM ancestors a "
                ") ranked "
                "JOIN symbols s ON ranked.aid = s.id "
                "WHERE ranked.rn = 1 AND s.kind = 'class' AND s.id != ? "
                "ORDER BY ranked.depth, s.fqn, s.id;",
                (symbol_id, max_depth, symbol_id),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "fqn": r["fqn"],
                "name": r["name"],
                "kind": r["kind"],
                "file_path": r["file_path"],
                "line_start": r["line_start"],
                "line_end": r["line_end"],
                "language": r["language"],
                "depth": r["depth"],
            }
            for r in rows
        ]

    def get_inheritance_targets(self, symbol_id: int) -> list[dict[str, Any]]:
        """Return the declared base types of *symbol_id* (resolved or external).

        Used by framework-aware analysis to recognise interfaces whose base
        types live outside the indexed corpus (for example a Spring Data
        repository extending ``JpaRepository``). Unresolved edges carry the
        raw base name in ``target_raw`` and are reported with ``resolved``
        ``False`` so callers can tell a local type from an external one.

        Args:
            symbol_id: The class/interface whose base clauses are requested.

        Returns:
            Base-type rows ``{name, fqn, resolved, relationship}`` ordered by
            the stored base name. ``name`` is the simple leaf name in either
            case and ``relationship`` is ``IMPLEMENTS`` or ``INHERITS``.
        """
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT e.resolved AS resolved, e.target_raw AS target_raw, "
                "e.edge_type AS relationship, s.fqn AS fqn, s.name AS name "
                "FROM graph_edges e "
                "LEFT JOIN symbols s ON s.id = e.target_symbol_id "
                "WHERE e.source_symbol_id = ? "
                "AND e.edge_type IN ('INHERITS', 'IMPLEMENTS') "
                "ORDER BY COALESCE(s.name, e.target_raw);",
                (symbol_id,),
            ).fetchall()
        targets: list[dict[str, Any]] = []
        for row in rows:
            raw = row["target_raw"] or row["fqn"] or ""
            leaf = raw.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
            targets.append(
                {
                    "name": row["name"] or leaf,
                    "fqn": row["fqn"],
                    "resolved": bool(row["resolved"]),
                    "relationship": row["relationship"],
                }
            )
        return targets


class ModuleEdgeStore:
    """CRUD and traversal for file/module-level ``module_edges`` rows."""

    def __init__(self, db: GraphDatabase) -> None:
        """Initialize the module-edge store over *db*."""
        self._db = db

    def insert_edges_batch(
        self, edges: list[dict[str, Any]], conn: sqlite3.Connection | None = None
    ) -> None:
        """Insert module edges, ignoring duplicates.

        Args:
            edges: Rows carrying ``source_path``, ``target_path``, ``relation``,
                optional ``target_raw``/``source_range``, and ``resolved``.
            conn: An existing writer connection to reuse; when ``None`` a fresh
                transaction is opened and committed.
        """
        if conn is not None:
            self._insert_rows(conn, edges)
            return
        with self._db.write_transaction() as owned:
            self._insert_rows(owned, edges)

    @staticmethod
    def _insert_rows(conn: sqlite3.Connection, edges: list[dict[str, Any]]) -> None:
        """Insert *edges* over *conn* without committing."""
        for edge in edges:
            conn.execute(
                "INSERT OR IGNORE INTO module_edges "
                "(source_path, target_path, relation, target_raw, resolved, source_range) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (
                    edge["source_path"],
                    edge.get("target_path"),
                    edge["relation"],
                    edge.get("target_raw"),
                    0 if edge.get("resolved") == 0 else 1,
                    edge.get("source_range"),
                ),
            )

    def get_importers(self, path: str, max_depth: int = 1) -> list[dict[str, Any]]:
        """Return files that import *path* (reverse ``IMPORTS`` traversal).

        Args:
            path: Index-root-relative POSIX path of the imported file.
            max_depth: Maximum reverse hops (clipped to 5).

        Returns:
            Rows ``{path, depth}`` ordered by depth then path, deduplicated at
            the shallowest depth.
        """
        return self._traverse_kind(path, "importers", max_depth)

    def get_imports(self, path: str, max_depth: int = 1) -> list[dict[str, Any]]:
        """Return files imported by *path* (forward ``IMPORTS`` traversal)."""
        return self._traverse_kind(path, "imports", max_depth)

    def _traverse_kind(self, path: str, kind: str, max_depth: int) -> list[dict[str, Any]]:
        """Run the forward or reverse ``IMPORTS`` recursive CTE."""
        depth = max(1, min(max_depth, 5))
        if kind == "importers":
            sql = (
                "WITH RECURSIVE walk AS ( "
                "SELECT e.source_path AS path, 1 AS depth, "
                "'|' || e.source_path || '|' AS trail "
                "FROM module_edges e "
                "WHERE e.target_path = ? AND e.relation = 'IMPORTS' "
                "UNION ALL "
                "SELECT e.source_path, w.depth + 1, w.trail || e.source_path || '|' "
                "FROM module_edges e JOIN walk w ON e.target_path = w.path "
                "WHERE e.relation = 'IMPORTS' AND w.depth < ? "
                "AND instr(w.trail, '|' || e.source_path || '|') = 0 "
                ") "
                "SELECT path, MIN(depth) AS depth FROM walk "
                "GROUP BY path ORDER BY depth, path;"
            )
        else:
            sql = (
                "WITH RECURSIVE walk AS ( "
                "SELECT e.target_path AS path, 1 AS depth, "
                "'|' || e.target_path || '|' AS trail "
                "FROM module_edges e "
                "WHERE e.source_path = ? AND e.relation = 'IMPORTS' "
                "AND e.target_path IS NOT NULL AND e.resolved = 1 "
                "UNION ALL "
                "SELECT e.target_path, w.depth + 1, w.trail || e.target_path || '|' "
                "FROM module_edges e JOIN walk w ON e.source_path = w.path "
                "WHERE e.relation = 'IMPORTS' AND w.depth < ? "
                "AND e.target_path IS NOT NULL AND e.resolved = 1 "
                "AND instr(w.trail, '|' || e.target_path || '|') = 0 "
                ") "
                "SELECT path, MIN(depth) AS depth FROM walk "
                "GROUP BY path ORDER BY depth, path;"
            )
        with self._db.connect() as conn:
            rows = conn.execute(sql, (path, depth)).fetchall()
        return [{"path": r["path"], "depth": r["depth"]} for r in rows]

    def all_edges(self, relation: str = "IMPORTS") -> list[dict[str, Any]]:
        """Return every module edge of *relation*, ordered deterministically."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT source_path, target_path, relation, target_raw, resolved "
                "FROM module_edges WHERE relation = ? "
                "ORDER BY source_path, target_path, target_raw;",
                (relation,),
            ).fetchall()
        return [dict(r) for r in rows]

    def resolution_stats(self, relation: str = "IMPORTS") -> dict[str, int]:
        """Return ``{total, resolved, unresolved}`` counts for *relation*."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(resolved), 0) AS resolved "
                "FROM module_edges WHERE relation = ?;",
                (relation,),
            ).fetchone()
        total = int(row["total"]) if row else 0
        resolved = int(row["resolved"]) if row else 0
        return {
            "total": total,
            "resolved": resolved,
            "unresolved": total - resolved,
        }


class RationaleStore:
    """CRUD for rationale comments linked to symbols."""

    def __init__(self, db: GraphDatabase) -> None:
        """Initialize the rationale store over *db*."""
        self._db = db

    def insert_batch(
        self, rows: list[dict[str, Any]], conn: sqlite3.Connection | None = None
    ) -> None:
        """Insert rationale rows, ignoring duplicates.

        Each row carries ``symbol_id``, ``file_path``, ``line_start``,
        ``line_end``, ``kind``, and ``text``.
        """
        if conn is not None:
            self._insert_rows(conn, rows)
            return
        with self._db.write_transaction() as owned:
            self._insert_rows(owned, rows)

    @staticmethod
    def _insert_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO symbol_rationale "
                "(symbol_id, file_path, line_start, line_end, kind, text) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (
                    row["symbol_id"],
                    row["file_path"],
                    row["line_start"],
                    row["line_end"],
                    row["kind"],
                    row["text"],
                ),
            )

    def for_symbol(self, symbol_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Return rationale rows attached to *symbol_id*, ordered by line."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT kind, file_path, line_start, line_end, text "
                "FROM symbol_rationale WHERE symbol_id = ? "
                "ORDER BY line_start, id LIMIT ?;",
                (symbol_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def for_file(self, file_path: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return rationale rows in *file_path*, ordered by line."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT kind, file_path, line_start, line_end, text "
                "FROM symbol_rationale WHERE file_path = ? "
                "ORDER BY line_start, id LIMIT ?;",
                (file_path, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search rationale comments via ``rationale_fts``."""
        match = " OR ".join(term for term in query.split() if term)
        if not match:
            return []
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT r.kind, r.file_path, r.line_start, r.line_end, r.text "
                "FROM rationale_fts f JOIN symbol_rationale r ON r.id = f.rowid "
                "WHERE rationale_fts MATCH ? LIMIT ?;",
                (match, limit),
            ).fetchall()
        return [dict(r) for r in rows]


class DocLinkStore:
    """CRUD for offline documentation/config-to-code links."""

    def __init__(self, db: GraphDatabase) -> None:
        """Initialize the doc-link store over *db*."""
        self._db = db

    def insert_batch(
        self, rows: list[dict[str, Any]], conn: sqlite3.Connection | None = None
    ) -> None:
        """Insert doc links, ignoring duplicates."""
        if conn is not None:
            self._insert_rows(conn, rows)
            return
        with self._db.write_transaction() as owned:
            self._insert_rows(owned, rows)

    @staticmethod
    def _insert_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO doc_links "
                "(doc_chunk_id, code_chunk_id, score, method) VALUES (?, ?, ?, ?);",
                (
                    row["doc_chunk_id"],
                    row["code_chunk_id"],
                    row["score"],
                    row["method"],
                ),
            )

    def for_code_chunk(self, code_chunk_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Return linked documentation for *code_chunk_id*, best score first."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT l.doc_chunk_id, l.score, l.method, c.file_path, c.line_start, "
                "c.line_end, c.content "
                "FROM doc_links l JOIN code_chunks c ON c.id = l.doc_chunk_id "
                "WHERE l.code_chunk_id = ? ORDER BY l.score DESC, l.doc_chunk_id LIMIT ?;",
                (code_chunk_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def for_file(self, file_path: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return links whose code chunk lives in *file_path*."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT l.doc_chunk_id, l.code_chunk_id, l.score, l.method, "
                "d.file_path AS doc_file_path, d.line_start AS doc_line_start "
                "FROM doc_links l "
                "JOIN code_chunks c ON c.id = l.code_chunk_id "
                "JOIN code_chunks d ON d.id = l.doc_chunk_id "
                "WHERE c.file_path = ? ORDER BY l.score DESC, l.doc_chunk_id LIMIT ?;",
                (file_path, limit),
            ).fetchall()
        return [dict(r) for r in rows]


class IndexMetadataStore:
    """Key-value store for index metadata (status, version, counts, etc.)."""

    def __init__(self, db: GraphDatabase) -> None:
        """Initialize the metadata store over a graph database.

        Args:
            db: The :class:`GraphDatabase` whose ``index_metadata`` table
                backs this store.
        """
        self._db = db

    def get(self, key: str) -> str | None:
        """Return the string value for *key*, or ``None`` when unset."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT value FROM index_metadata WHERE key = ?;", (key,)).fetchone()
            return row["value"] if row else None

    def get_int(self, key: str) -> int | None:
        """Return the integer value for *key*, or ``None`` when unset/empty."""
        val = self.get(key)
        return int(val) if val is not None else None

    def get_json(self, key: str) -> Any:
        """Return the JSON-decoded value for *key*, or ``None`` when unset."""
        val = self.get(key)
        return json.loads(val) if val is not None else None

    def set(self, key: str, value: str) -> None:
        """Upsert the string *value* under *key*."""
        with self._db.write_transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO index_metadata (key, value) VALUES (?, ?);",
                (key, value),
            )

    def set_int(self, key: str, value: int) -> None:
        """Upsert the integer *value* under *key*."""
        self.set(key, str(value))

    def set_json(self, key: str, value: Any) -> None:
        """JSON-serialise *value* and upsert it under *key*."""
        self.set(key, json.dumps(value))

    def get_all(self) -> dict[str, str]:
        """Return every key/value pair currently stored."""
        with self._db.connect() as conn:
            rows = conn.execute("SELECT key, value FROM index_metadata;").fetchall()
            return {row["key"]: row["value"] for row in rows}

    def get_index_status(self) -> str:
        """Return the lifecycle ``index_status`` value (default ``unindexed``)."""
        return self.get("index_status") or "unindexed"

    def set_index_status(self, status: str) -> None:
        """Set the lifecycle ``index_status``, validating against the enum.

        Args:
            status: One of ``unindexed``, ``indexing``, ``ready``, ``stale``,
                ``error``.

        Raises:
            ValueError: When *status* is not a valid lifecycle value.
        """
        valid_statuses = {"unindexed", "indexing", "ready", "stale", "error"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid index status: {status}. Must be one of {valid_statuses}")
        self.set("index_status", status)

    def get_fts_chunks(self) -> int | None:
        """Return the recorded ``chunks_fts`` row count, or ``None`` if unset."""
        return self.get_int("fts_chunks")

    def set_fts_chunks(self, count: int) -> None:
        """Record the number of rows in ``chunks_fts`` for parity verification."""
        self.set_int("fts_chunks", count)
