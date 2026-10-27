"""Schema v7 -> v12 migration tests.

v8 adds nullable ``size``/``file_mtime_ns`` stat-baseline columns to
``file_checksums`` for the freshness stat fast-path. Existing v7 rows keep
``NULL`` baselines (self-healed on first freshness scan) and the migration
path marks the index lifecycle status ``stale`` (re-index recommended).
v9 carries no DDL change: it caps the append/tombstone vector-store layout,
so the bump surfaces as an ``index_version`` value plus a forced re-index.
v10 adds nullable ``declared_rules`` to ``code_chunks``/``symbols`` and
rebuilds ``chunks_fts`` with the new fifth column.
v11 adds the ``parse_failed`` flag column to ``file_checksums`` so
enumerate mode can report structurally unparseable files.
v12 adds ``code_chunks.content_type``, ``graph_edges.resolved`` /
``graph_edges.target_raw``, makes ``graph_edges.target_symbol_id`` nullable
and rebuilds ``chunks_fts`` with the new content axis column.
v17 deduplicates unresolved edges and creates the partial unique index that
prevents them from multiplying, and adds the ``index_coverage`` table.
v18 adds the edge ``properties`` column, widens the edge-type CHECK, adds the
symbol trust columns (``canonical_fqn``, ``visibility``, ``is_test``,
``is_entry_point``, ``entry_point_reason``, ``importance``), and creates the
derived ``symbol_degrees`` table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from code_search.engine.config import Settings
from code_search.engine.graph import (
    ALL_DDLS,
    CODE_CHUNKS_TABLE_DDL,
    SYMBOLS_TABLE_DDL,
    GraphDatabase,
)

V7_FILE_CHECKSUMS_DDL = """
CREATE TABLE IF NOT EXISTS file_checksums (
    file_path TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    last_modified TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""


def _strip_declared_rules(ddl: str) -> str:
    """Return *ddl* with the v10 ``declared_rules`` column removed (v9 shape)."""
    return ddl.replace("    declared_rules TEXT,\n", "")


def _build_v7_database(db_path: Path) -> None:
    """Create a database matching the pre-v8 schema with a seed checksum row."""
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            if "chunks_fts" in ddl:
                continue
            if ddl.strip().startswith("CREATE TABLE") and "file_checksums" in ddl:
                conn.execute(V7_FILE_CHECKSUMS_DDL)
            elif ddl.strip() in (SYMBOLS_TABLE_DDL.strip(), CODE_CHUNKS_TABLE_DDL.strip()):
                conn.execute(_strip_declared_rules(ddl))
            else:
                conn.execute(ddl)
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_version', '7');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_status', 'ready');")
        conn.execute(
            "INSERT INTO file_checksums (file_path, checksum, last_modified) VALUES (?, ?, ?);",
            ("/repo/src/a.py", "abc123", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _file_checksums_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(file_checksums);").fetchall()}
        return cols
    finally:
        conn.close()


def _table_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    finally:
        conn.close()


def _index_sql(db_path: Path, index: str) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?;",
            (index,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_v7_database_migrates_to_v19(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.db"
    _build_v7_database(db_path)

    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    cols = _file_checksums_columns(db_path)
    assert "size" in cols
    assert "file_mtime_ns" in cols
    assert "parse_failed" in cols

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM file_checksums;").fetchone()
        assert row is not None
        assert row["file_path"] == "/repo/src/a.py"
        assert row["checksum"] == "abc123"
        assert row["size"] is None
        assert row["file_mtime_ns"] is None
        assert row["parse_failed"] == 0
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()
        assert version is not None
        assert int(version["value"]) == 19
        status = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_status';"
        ).fetchone()
        assert status is not None
        assert status["value"] == "stale"
    finally:
        conn.close()


def test_fresh_database_has_v19_schema_in_base_ddl(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.db"
    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    cols = _file_checksums_columns(db_path)
    assert "size" in cols
    assert "file_mtime_ns" in cols
    assert "parse_failed" in cols

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()
        assert version is not None
        assert int(version["value"]) == 19
        assert "content_type" in _table_columns(db_path, "code_chunks")
        assert "is_test" in _table_columns(db_path, "code_chunks")
        edge_cols = _table_columns(db_path, "graph_edges")
        assert "resolved" in edge_cols
        assert "target_raw" in edge_cols
    finally:
        conn.close()


def test_v9_database_gains_declared_rules_and_fts_parity(tmp_path: Path) -> None:
    """v9 -> v13: the migration adds ``declared_rules`` to
    ``code_chunks``/``symbols`` and rebuilds ``chunks_fts`` with the column."""
    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            if "chunks_fts" in ddl:
                continue
            if ddl.strip() in (SYMBOLS_TABLE_DDL.strip(), CODE_CHUNKS_TABLE_DDL.strip()):
                conn.execute(_strip_declared_rules(ddl))
            else:
                conn.execute(ddl)
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_version', '9');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_status', 'ready');")
        conn.commit()
    finally:
        conn.close()

    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    assert "declared_rules" in _table_columns(db_path, "code_chunks")
    assert "declared_rules" in _table_columns(db_path, "symbols")
    assert "parse_failed" in _file_checksums_columns(db_path)
    assert "content_type" in _table_columns(db_path, "code_chunks")
    assert "is_test" in _table_columns(db_path, "code_chunks")
    edge_cols = _table_columns(db_path, "graph_edges")
    assert "resolved" in edge_cols
    assert "target_raw" in edge_cols

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()
        assert int(version["value"]) == 19
        fts = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'chunks_fts';").fetchone()
        assert fts is not None and "declared_rules" in fts["sql"]
        assert "content_type" in fts["sql"]
        assert "file_path" not in fts["sql"]
        paths = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'paths_fts';").fetchone()
        assert paths is not None and "file_path" in paths["sql"]
        code_count = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        fts_count = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
        paths_count = conn.execute("SELECT COUNT(*) AS n FROM paths_fts;").fetchone()["n"]
        assert code_count == fts_count == paths_count
    finally:
        conn.close()


def test_fresh_database_accepts_duplicate_conventional_fqns(tmp_path: Path) -> None:
    """Conventional FQNs may collide; both symbols must be stored."""
    db_path = tmp_path / "graph.db"
    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    index_sql = _index_sql(db_path, "idx_symbols_conventional_fqn")
    assert index_sql is not None
    assert "UNIQUE" not in index_sql.upper()

    conn = sqlite3.connect(str(db_path))
    try:
        for symbol_id, file_path in (
            (1, "/repo/a/IdentityProfile.java"),
            (2, "/repo/b/IdentityProfile.java"),
        ):
            conn.execute(
                "INSERT INTO symbols "
                "(id, fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, conventional_fqn) "
                "VALUES (?, ?, 'displayName', 'method', ?, 1, 1, 0, 0, 'java', "
                "'com.example.IdentityProfile.displayName');",
                (symbol_id, f"{file_path}::IdentityProfile.displayName", file_path),
            )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM symbols "
            "WHERE conventional_fqn = 'com.example.IdentityProfile.displayName';"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_v15_database_drops_unique_conventional_fqn_index(tmp_path: Path) -> None:
    """A v15 database's unique conventional-FQN index becomes non-unique."""
    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            conn.execute(ddl)
        conn.execute("DROP INDEX idx_symbols_conventional_fqn;")
        conn.execute(
            "CREATE UNIQUE INDEX idx_symbols_conventional_fqn ON symbols(conventional_fqn);"
        )
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_version', '15');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_status', 'ready');")
        conn.commit()
    finally:
        conn.close()

    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    index_sql = _index_sql(db_path, "idx_symbols_conventional_fqn")
    assert index_sql is not None
    assert "UNIQUE" not in index_sql.upper()


def test_v16_database_deduplicates_unresolved_edges(tmp_path: Path) -> None:
    """The v17 migration collapses duplicate unresolved edges before indexing.

    SQLite's table-level UNIQUE ignores NULL targets, so a v16 database can
    hold one row per repeated external reference. The migration keeps the
    oldest row per ``(source, edge_type, target_raw)`` and installs the partial
    unique index that prevents recurrence.
    """
    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (1, '/repo/a.py::caller', 'caller', 'function', '/repo/a.py', 1, 4, 0, 0, "
            "'python');"
        )
        conn.executemany(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, target_raw) "
            "VALUES (1, NULL, 'CALLS', 0, 'external.save');",
            [()] * 3,
        )
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_version', '16');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_status', 'ready');")
        conn.commit()
    finally:
        conn.close()

    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE target_symbol_id IS NULL;"
        ).fetchone()[0]
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    assert int(version) == 19
    assert _index_sql(db_path, "idx_edges_unique_unresolved") is not None
