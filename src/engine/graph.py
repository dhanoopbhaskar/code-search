"""Graph database — SQLite-backed schema for symbols, code chunks, edges, and metadata.

Manages:
- ``symbols`` — function/class/method/etc. definitions with FQN, location, docstring.
- ``graph_edges`` — typed directed edges (CALLS, IMPORTS, INHERITS, REFERENCES).
- ``code_chunks`` — extracted code chunks (AST or fallback) with FTS5 full-text search.
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

from src.engine.config import Settings
from src.engine.symbol_resolution import (
    parse_reference,
    resolve_reference,
    strip_params,
    symbol_leaf,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 13
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
    parent_symbol_id INTEGER REFERENCES symbols(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

SYMBOLS_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_conventional_fqn ON symbols(conventional_fqn);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_file_path ON symbols(file_path);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_symbol_id);",
]

GRAPH_EDGES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    target_symbol_id INTEGER REFERENCES symbols(id),
    edge_type TEXT NOT NULL CHECK(edge_type IN ('CALLS','IMPORTS','INHERITS','REFERENCES')),
    source_range TEXT,
    target_range TEXT,
    resolution_tier TEXT,
    resolved INTEGER NOT NULL DEFAULT 1,
    target_raw TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source_symbol_id, target_symbol_id, edge_type)
);
"""

GRAPH_EDGES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_symbol_id);",
    "CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_symbol_id);",
    "CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);",
    "CREATE INDEX IF NOT EXISTS idx_edges_source_type ON graph_edges(source_symbol_id, edge_type);",
    "CREATE INDEX IF NOT EXISTS idx_edges_target_type ON graph_edges(target_symbol_id, edge_type);",
]

CODE_CHUNKS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS code_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fqn TEXT,
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(file_path, line_start)
);
"""

CODE_CHUNKS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_chunks_file_line ON code_chunks(file_path, line_start);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_fqn ON code_chunks(fqn);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_definition ON code_chunks(is_definition);",
]

CHUNKS_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    subwords,
    fqn,
    file_path,
    declared_rules,
    content_type,
    content=code_chunks,
    content_rowid=id
);
"""

# FTS5 external-content maintenance triggers: keep chunks_fts in sync with
# code_chunks on every insert/delete/update so the keyword index cannot drift.
CHUNKS_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON code_chunks BEGIN
        INSERT INTO chunks_fts(rowid, content, subwords, fqn, file_path, declared_rules,
                               content_type)
        VALUES (new.id, new.content, new.subwords, new.fqn, new.file_path,
                new.declared_rules, new.content_type);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON code_chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, subwords, fqn, file_path,
                               declared_rules, content_type)
        VALUES ('delete', old.id, old.content, old.subwords, old.fqn, old.file_path,
                old.declared_rules, old.content_type);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON code_chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, subwords, fqn, file_path,
                               declared_rules, content_type)
        VALUES ('delete', old.id, old.content, old.subwords, old.fqn, old.file_path,
                old.declared_rules, old.content_type);
        INSERT INTO chunks_fts(rowid, content, subwords, fqn, file_path, declared_rules,
                               content_type)
        VALUES (new.id, new.content, new.subwords, new.fqn, new.file_path,
                new.declared_rules, new.content_type);
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

ALL_DDLS = [
    SYMBOLS_TABLE_DDL,
    *SYMBOLS_INDEXES,
    GRAPH_EDGES_TABLE_DDL,
    *GRAPH_EDGES_INDEXES,
    CODE_CHUNKS_TABLE_DDL,
    *CODE_CHUNKS_INDEXES,
    CHUNKS_FTS_DDL,
    *CHUNKS_FTS_TRIGGERS,
    FILE_CHECKSUMS_TABLE_DDL,
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
    base_rows = conn.execute(
        "SELECT s.*, p.name AS parent_name, p.kind AS parent_kind, "
        "p.fqn AS parent_fqn "
        "FROM symbols s LEFT JOIN symbols p ON s.parent_symbol_id = p.id "
        "WHERE s.fqn = ? OR s.name = ? OR s.name = ? "
        "OR s.fqn LIKE '%::' || ? OR s.conventional_fqn LIKE '%' || ? "
        "ORDER BY s.id LIMIT 100;",
        (query, query, leaf, query, query),
    ).fetchall()
    if base_rows:
        return [dict(r) for r in base_rows]

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

    Delegates to the pure :func:`src.engine.symbol_resolution.resolve_reference`
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

        Returns:
            A configured ``sqlite3.Connection`` usable from any thread
            (``check_same_thread=False``).
        """
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        """Create all tables, indexes, and triggers; record or validate schema version."""
        with self._write_lock:
            conn = self._create_connection()
            try:
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
                        conn.execute(
                            "UPDATE index_metadata SET value = ? WHERE key = 'index_version';",
                            (str(SCHEMA_VERSION),),
                        )
                        conn.execute(
                            "UPDATE index_metadata SET value = 'stale' WHERE key = 'index_status';"
                        )
                conn.commit()
            finally:
                conn.close()
            self._local.conn = None

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
        """Clear and repopulate ``chunks_fts`` from ``code_chunks``.

        Uses the FTS5 ``rebuild`` command, which resyncs the external-content
        index from the content table, then returns the resulting row count so
        callers can verify ``COUNT(code_chunks) == COUNT(chunks_fts)`` parity.
        """
        with self._write_lock:
            conn = self._create_connection()
            try:
                conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")
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
    ) -> int | None:
        """Insert a single directed edge between two symbols.

        Validates *edge_type* against ``{CALLS, IMPORTS, INHERITS,
        REFERENCES}`` and skips self-loops (``source == target``), which are
        not representable per the schema design.

        Args:
            source_symbol_id: The caller/referencing symbol id.
            target_symbol_id: The callee/referenced symbol id.
            edge_type: One of the valid edge kinds.
            source_range: JSON ``[s_line, s_col, e_line, e_col]`` call range.
            target_range: JSON target range, when known.
            resolution_tier: Confidence tier (e.g. ``exact``, ``fallback``).

        Returns:
            The new row id, or ``None`` when the edge is skipped or the
            insert fails.
        """
        valid_types = {"CALLS", "IMPORTS", "INHERITS", "REFERENCES"}
        if edge_type not in valid_types:
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
                    "target_range, resolution_tier) "
                    "VALUES (?, ?, ?, ?, ?, ?);",
                    (
                        source_symbol_id,
                        target_symbol_id,
                        edge_type,
                        source_range,
                        target_range,
                        resolution_tier,
                    ),
                )
                return cursor.lastrowid
            except Exception as exc:
                logger.warning("Failed to insert edge: %s", exc)
                return None

    def insert_edges_batch(self, edges: list[dict[str, Any]]) -> None:
        """Insert many edges at once, guarding against spurious self-edges.

        Mirrors ``insert_edge``'s ``source == target`` guard: a
        ``source_symbol_id == target_symbol_id`` edge is a spurious
        self-resolution (same-name look-alike) and is skipped unless the
        caller explicitly marks it as a genuine recursive self-call
        (``recursive=True``).
        """
        with self._db.write_transaction() as conn:
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
                        "resolved, target_raw) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                        (
                            src_id,
                            tgt_id,
                            edge["edge_type"],
                            edge.get("source_range"),
                            edge.get("target_range"),
                            edge.get("resolution_tier"),
                            0 if edge.get("resolved") == 0 else 1,
                            edge.get("target_raw"),
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
        from src.engine.symbols import SymbolStore

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
    ) -> dict[str, list[dict[str, Any]]]:
        """Traverse callers and/or callees via recursive CTE, clipped to *max_depth*."""
        result: dict[str, list[dict[str, Any]]] = {"callers": [], "callees": []}
        clipped_depth = min(max_depth, 5)

        with self._db.connect() as conn:
            if direction in ("both", "callers"):
                result["callers"] = self._traverse_callers(conn, symbol_id, clipped_depth)

            if direction in ("both", "callees"):
                result["callees"] = self._traverse_callees(conn, symbol_id, clipped_depth)

        return result

    def _traverse_callers(
        self, conn: sqlite3.Connection, symbol_id: int, max_depth: int
    ) -> list[dict[str, Any]]:
        """Return symbols that transitively call *symbol_id*, with minimum depth.

        Uses a recursive CTE that walks ``CALLS`` edges backwards from the
        target, pruning at *max_depth* and breaking cycles via an ancestor
        path guard. Cycle presence is additionally detected and logged at
        debug level.

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
            Deduplicated caller rows ``{fqn, kind, file_path, line_start,
            source_range, depth}`` ordered by depth, then FQN, then symbol id.
        """
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
            "ranked.source_range, ranked.depth "
            "FROM ( "
            "SELECT c.caller_id, c.source_range, c.depth, "
            "ROW_NUMBER() OVER ( "
            "PARTITION BY c.caller_id ORDER BY c.depth, c.source_range "
            ") AS rn "
            "FROM callers c "
            ") ranked "
            "JOIN symbols s ON ranked.caller_id = s.id "
            "WHERE ranked.rn = 1 "
            "ORDER BY ranked.depth, s.fqn, ranked.caller_id;",
            (symbol_id, max_depth),
        ).fetchall()
        # Log cycle detection info
        all_rows = conn.execute(
            "WITH RECURSIVE callers AS ( "
            "SELECT e.source_symbol_id AS caller_id, 1 AS depth, "
            "'|' || e.source_symbol_id || '|' AS path "
            "FROM graph_edges e "
            "WHERE e.target_symbol_id = ? AND e.edge_type = 'CALLS' "
            "UNION ALL "
            "SELECT e.source_symbol_id, c.depth + 1, "
            "c.path || e.source_symbol_id || '|' "
            "FROM graph_edges e "
            "JOIN callers c ON e.target_symbol_id = c.caller_id "
            "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
            "AND instr(c.path, '|' || e.source_symbol_id || '|') > 0 "
            ") "
            "SELECT source_symbol_id, depth FROM callers c "
            "JOIN graph_edges e ON c.caller_id = e.source_symbol_id;",
            (symbol_id, max_depth),
        ).fetchall()
        if all_rows:
            logger.debug(
                "Cycle(s) detected in caller traversal for symbol %d at depths %s",
                symbol_id,
                sorted({r["depth"] for r in all_rows}),
            )
        return self._attach_edge_signature(
            conn, symbol_id, [dict(r) for r in rows], is_callee_traversal=False
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
        self, conn: sqlite3.Connection, symbol_id: int, max_depth: int
    ) -> list[dict[str, Any]]:
        """Return symbols that *symbol_id* transitively calls, with minimum depth.

        The forward mirror of :meth:`_traverse_callers`: a recursive CTE walks
        ``CALLS`` edges from the source, pruning at *max_depth* and breaking
        cycles via an ancestor path guard. Cycle presence is detected and
        logged at debug level.

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
            Deduplicated callee rows ``{fqn, conventional_fqn, kind,
            file_path, line_start, callee_id, target_range, depth, resolved,
            target_raw}`` ordered by depth, then FQN (falling back to the raw
            target), then symbol id.
        """
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
            "ranked.resolved, ranked.target_raw "
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
            "ORDER BY ranked.depth, COALESCE(s.fqn, ranked.target_raw), ranked.callee_id;",
            (symbol_id, max_depth),
        ).fetchall()
        # Log cycle detection info
        all_rows = conn.execute(
            "WITH RECURSIVE callees AS ( "
            "SELECT e.target_symbol_id AS callee_id, 1 AS depth, "
            "'|' || e.target_symbol_id || '|' AS path "
            "FROM graph_edges e "
            "WHERE e.source_symbol_id = ? AND e.edge_type = 'CALLS' "
            "UNION ALL "
            "SELECT e.target_symbol_id, c.depth + 1, "
            "c.path || COALESCE(e.target_symbol_id, 'u') || '|' "
            "FROM graph_edges e "
            "JOIN callees c ON e.source_symbol_id = c.callee_id "
            "WHERE e.edge_type = 'CALLS' AND c.depth < ? "
            "AND instr(c.path, '|' || COALESCE(e.target_symbol_id, 'u') || '|') > 0 "
            ") "
            "SELECT target_symbol_id, depth FROM callees c "
            "JOIN graph_edges e ON c.callee_id = e.target_symbol_id;",
            (symbol_id, max_depth),
        ).fetchall()
        if all_rows:
            logger.debug(
                "Cycle(s) detected in callee traversal for symbol %d at depths %s",
                symbol_id,
                sorted({r["depth"] for r in all_rows}),
            )
        shaped: list[dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            unresolved = row.get("resolved") == 0 or row.get("fqn") is None
            row["resolved"] = not unresolved
            row["target_raw"] = row.get("target_raw") if unresolved else None
            if unresolved:
                row["fqn"] = row.get("target_raw") or "<unresolved callee>"
                row["kind"] = "external"
                row["file_path"] = None
                row["line_start"] = None
            shaped.append(row)
        return self._attach_edge_signature(conn, symbol_id, shaped, is_callee_traversal=True)

    def get_subtypes(self, symbol_id: int, max_depth: int = 5) -> list[dict[str, Any]]:
        """Return types that inherit from *symbol_id*, with minimum depth.

        Walks ``INHERITS`` edges **backwards** (base -> subtype) with a
        recursive CTE: the seed matches ``target_symbol_id = symbol_id`` and
        each recursion follows ``target_symbol_id = previous source``. The walk
        is bounded by *max_depth* and terminated on cycles by an ancestor path
        guard, so a self-inheriting or mutually-recursive hierarchy cannot loop.

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
            line_end, language, depth, path}`` ordered by depth, then kind,
            then FQN, then id. ``depth`` is 1 for a direct subtype and greater
            than 1 for an indirect one; ``path`` is the FQN chain from the
            queried base to the subtype.
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
                "'|' || e.source_symbol_id || '|' AS cpath, "
                "s.fqn AS fqn_path "
                "FROM graph_edges e INDEXED BY idx_edges_target_type "
                "JOIN symbols s ON s.id = e.source_symbol_id "
                "WHERE e.target_symbol_id = ? AND e.edge_type = 'INHERITS' "
                "UNION ALL "
                "SELECT e.source_symbol_id, st.depth + 1, "
                "st.cpath || e.source_symbol_id || '|', "
                "st.fqn_path || '>' || s.fqn "
                "FROM graph_edges e INDEXED BY idx_edges_target_type "
                "JOIN subtypes st ON e.target_symbol_id = st.sid "
                "JOIN symbols s ON s.id = e.source_symbol_id "
                "WHERE e.edge_type = 'INHERITS' AND st.depth < ? "
                "AND instr(st.cpath, '|' || e.source_symbol_id || '|') = 0 "
                ") "
                "SELECT s.id, s.fqn, s.name, s.kind, s.file_path, s.line_start, "
                "s.line_end, s.language, ranked.depth, ranked.fqn_path "
                "FROM ( "
                "SELECT st.sid, st.depth, st.fqn_path, "
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
