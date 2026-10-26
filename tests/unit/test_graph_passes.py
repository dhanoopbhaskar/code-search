"""Phase 2 edge-model, entry-point, importance, and dead-code tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from code_search.engine.config import Settings
from code_search.engine.graph import ALL_DDLS, SCHEMA_VERSION, GraphDatabase
from code_search.engine.graph_surface import find_dead_code, search_symbols
from code_search.engine.implementations import find_implementations

V17_SYMBOLS_DDL = """
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

V17_EDGES_DDL = """
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


def _edge_rows(db: GraphDatabase, edge_type: str) -> list[Any]:
    """Return resolved edges of *edge_type* as ``(source, target)`` name pairs."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT src.name AS source, tgt.name AS target, "
            "e.resolution_tier, e.properties "
            "FROM graph_edges e "
            "JOIN symbols src ON src.id = e.source_symbol_id "
            "JOIN symbols tgt ON tgt.id = e.target_symbol_id "
            "WHERE e.edge_type = ? AND e.resolved = 1 "
            "ORDER BY src.fqn, tgt.fqn;",
            (edge_type,),
        ).fetchall()


def _symbol_id(db: GraphDatabase, suffix: str) -> int:
    """Return the id of the unique symbol whose FQN ends with *suffix*."""
    with db.connect() as conn:
        rows = conn.execute("SELECT id FROM symbols WHERE fqn LIKE ?;", (f"%{suffix}",)).fetchall()
    assert len(rows) == 1, f"{suffix} must be unique, found {len(rows)}"
    return int(rows[0]["id"])


def test_implements_inherits_and_tests_edges(indexed_graph_edges: dict[str, Any]) -> None:
    """Class/interface relationships are separated and test edges are derived."""
    db = indexed_graph_edges["db"]

    implements = {(row["source"], row["target"]) for row in _edge_rows(db, "IMPLEMENTS")}
    assert ("Service", "Api") in implements
    assert ("TsService", "TsApi") in implements

    inherits = {(row["source"], row["target"]) for row in _edge_rows(db, "INHERITS")}
    assert ("Special", "Repo") in inherits
    assert ("Service", "Api") not in inherits

    tests = {(row["source"], row["target"]) for row in _edge_rows(db, "TESTS")}
    assert ("testRun", "Service") in tests
    assert ("testRun", "Repo") in tests


def test_reference_usage_and_call_reference_edges(
    indexed_graph_edges: dict[str, Any],
) -> None:
    """Callables used as values, member usage, and annotations are distinct."""
    db = indexed_graph_edges["db"]

    call_references = {(row["source"], row["target"]) for row in _edge_rows(db, "CALL_REFERENCE")}
    assert ("save", "py_handler") in call_references

    usages = {(row["source"], row["target"]) for row in _edge_rows(db, "USAGE")}
    assert ("run", "repo") in usages
    assert ("helper", "repo") in usages

    references = {(row["source"], row["target"]) for row in _edge_rows(db, "REFERENCES")}
    assert ("save", "PyArticle") in references
    assert ("run", "TsArticle") in references


def test_ambiguous_reference_stays_unresolved(indexed_graph_edges: dict[str, Any]) -> None:
    """A same-name reference with two candidates is never attached to the first."""
    db = indexed_graph_edges["db"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT e.resolved, e.resolution_tier, e.target_raw, e.properties "
            "FROM graph_edges e JOIN symbols s ON s.id = e.source_symbol_id "
            "WHERE s.name = 'call_shared' AND e.edge_type = 'CALLS';"
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["resolved"] == 0
    assert row["resolution_tier"] == "ambiguous"
    assert row["target_raw"] == "shared"
    assert json.loads(row["properties"])["candidate_count"] == 2


def test_entry_point_classification_is_stored(indexed_graph_edges: dict[str, Any]) -> None:
    """Tests, main, constructors, overrides, annotations, and export are classified."""
    db = indexed_graph_edges["db"]
    with db.connect() as conn:
        rows = {
            (row["name"], row["kind"]): (row["entry_point_reason"], row["is_test"])
            for row in conn.execute(
                "SELECT name, kind, entry_point_reason, is_test FROM symbols "
                "WHERE is_entry_point = 1 OR name = '_dead_function';"
            )
        }

    assert rows[("Api", "interface")] == ("exported", 0)
    assert rows[("Service", "constructor")] == ("constructor", 0)
    assert rows[("__init__", "method")] == ("constructor", 0)
    assert rows[("run", "method")] == ("override", 0)
    assert rows[("endpoint", "method")] == ("annotation", 0)
    assert rows[("testRun", "method")] == ("test", 1)
    assert rows[("_dead_function", "function")] == (None, 0)


def test_importance_and_degrees_are_stored(indexed_graph_edges: dict[str, Any]) -> None:
    """Stored degrees and importance are derived from resolved edges only."""
    db = indexed_graph_edges["db"]
    save_id = _symbol_id(db, "Repo.save(Article)")
    with db.connect() as conn:
        degree = conn.execute(
            "SELECT in_count, out_count FROM symbol_degrees "
            "WHERE symbol_id = ? AND edge_type = 'CALLS';",
            (save_id,),
        ).fetchone()
        importance = conn.execute(
            "SELECT importance, canonical_fqn FROM symbols WHERE id = ?;", (save_id,)
        ).fetchone()
        format_version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_format_version';"
        ).fetchone()

    assert degree is not None
    assert degree["in_count"] >= 1
    assert importance is not None
    assert importance["importance"] > 0
    assert importance["canonical_fqn"].startswith("src/main/java/com/example/Repo.java::")
    assert format_version is not None
    assert int(format_version["value"]) >= 1


def test_find_dead_code_reports_evidence_and_exclusions(
    indexed_graph_edges: dict[str, Any],
) -> None:
    """Dead-code candidates carry confidence, test-only use, and unresolved evidence."""
    db = indexed_graph_edges["db"]
    payload = find_dead_code(
        db,
        limit=100,
        index_root=indexed_graph_edges["repo"],
    )

    by_name = {candidate["name"]: candidate for candidate in payload["candidates"]}
    assert {"_dead_function", "dead", "trulyDead", "helper", "orphan"} <= set(by_name)
    assert "run" not in by_name  # override entry point
    assert "endpoint" not in by_name  # annotated entry point
    assert "testRun" not in by_name  # test symbol
    candidate_fqns = {candidate["fqn"] for candidate in payload["candidates"]}
    assert not any(fqn.endswith("Repo.save(Article)") for fqn in candidate_fqns)
    assert not any(fqn.endswith("Repo.persist(Article)") for fqn in candidate_fqns)

    assert by_name["_dead_function"]["confidence"] == "high"
    assert by_name["orphan"]["confidence"] == "medium"
    assert by_name["orphan"]["incoming"]["unresolved_same_name"] == 1
    assert payload["outcome"] == "resolved"
    assert payload["total"] == len(payload["candidates"])
    assert payload["truncated"] is False
    assert "absence is not proof of completeness" in payload["note"]

    include_all = find_dead_code(db, include_entry_points=True, include_tests=True, limit=200)
    all_names = {candidate["name"] for candidate in include_all["candidates"]}
    assert "testRun" in all_names
    assert "run" in all_names


def test_search_symbols_uses_stored_order_and_entry_points(
    indexed_graph_edges: dict[str, Any],
) -> None:
    """Stored importance orders results and stored entry points filter by default."""
    db = indexed_graph_edges["db"]
    default = search_symbols(db, kind=["class"])
    assert default["symbols"] == []

    included = search_symbols(db, kind=["class"], exclude_entry_points=False)
    names = {entry["name"] for entry in included["symbols"]}
    assert {"Repo", "Service", "Orphan"} <= names
    assert all(entry["importance"] is not None for entry in included["symbols"])

    ordered = search_symbols(
        db,
        name_pattern=r"save|dead|orphan",
        exclude_entry_points=False,
    )
    importances = [entry["importance"] for entry in ordered["symbols"]]
    assert importances == sorted(importances, reverse=True)


def test_find_implementations_prefers_implements(indexed_graph_edges: dict[str, Any]) -> None:
    """Implementation lookup reaches an IMPLEMENTS-only subtype."""
    result = find_implementations(
        indexed_graph_edges["symbol_store"],
        indexed_graph_edges["edge_store"],
        "Api.java::Api.run",
    )

    assert result["outcome"] == "resolved"
    implementers = {row["type"]["name"] for row in result["implementations"]}
    assert "Service" in implementers
    service = next(row for row in result["implementations"] if row["type"]["name"] == "Service")
    assert service["type"]["edge_relationship"] == "IMPLEMENTS"


def test_v16_database_migrates_through_v17_to_v18(tmp_path: Path) -> None:
    """A v16 index with duplicate unresolved edges reaches v18 in one open."""
    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            if "CREATE TABLE IF NOT EXISTS symbols" in ddl:
                conn.execute(V17_SYMBOLS_DDL)
                continue
            if "CREATE TABLE IF NOT EXISTS graph_edges" in ddl:
                conn.execute(V17_EDGES_DDL)
                continue
            if "symbol_degrees" in ddl:
                continue
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (1, '/repo/a.py::caller', 'caller', 'function', '/repo/a.py', "
            "1, 4, 0, 0, 'python');"
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
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()["value"]
        status = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_status';"
        ).fetchone()["value"]
        unresolved = conn.execute(
            "SELECT COUNT(*) AS n FROM graph_edges WHERE target_symbol_id IS NULL;"
        ).fetchone()["n"]
        properties = conn.execute(
            "SELECT properties FROM graph_edges WHERE target_symbol_id IS NULL LIMIT 1;"
        ).fetchone()["properties"]
        degrees = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'symbol_degrees';"
        ).fetchone()
    finally:
        conn.close()

    assert int(version) == SCHEMA_VERSION
    assert status == "stale"
    assert unresolved == 1
    assert properties == "{}"
    assert degrees is not None


def test_v17_database_migrates_to_v18(tmp_path: Path) -> None:
    """A v17 index gains columns, properties, and a widened edge CHECK."""
    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    try:
        for ddl in ALL_DDLS:
            if ddl.strip() == V17_SYMBOLS_DDL.strip() or ddl.strip() == V17_EDGES_DDL.strip():
                continue
            if "idx_symbols_canonical_fqn" in ddl or "symbol_degrees" in ddl:
                continue
            if "CREATE TABLE IF NOT EXISTS symbols" in ddl:
                conn.execute(V17_SYMBOLS_DDL)
                continue
            if "CREATE TABLE IF NOT EXISTS graph_edges" in ddl:
                conn.execute(V17_EDGES_DDL)
                continue
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn) "
            "VALUES (1, '/repo/src/Service.java::Service', 'Service', 'class', "
            "'/repo/src/Service.java', 1, 9, 0, 0, 'java', 'com.example.Service');"
        )
        conn.execute(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolved, target_raw) "
            "VALUES (1, NULL, 'CALLS', 0, 'external.save');"
        )
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_version', '17');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_status', 'ready');")
        conn.execute("INSERT INTO index_metadata (key, value) VALUES ('index_root', '/repo');")
        conn.commit()
    finally:
        conn.close()

    db = GraphDatabase(db_path, Settings(context_dir=tmp_path))
    db.initialize()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        symbol_columns = {row["name"] for row in conn.execute("PRAGMA table_info(symbols);")}
        edge_columns = {row["name"] for row in conn.execute("PRAGMA table_info(graph_edges);")}
        version = conn.execute(
            "SELECT value FROM index_metadata WHERE key = 'index_version';"
        ).fetchone()["value"]
        canonical = conn.execute(
            "SELECT canonical_fqn, is_test, is_entry_point, importance FROM symbols WHERE id = 1;"
        ).fetchone()
        properties = conn.execute(
            "SELECT properties FROM graph_edges WHERE target_symbol_id IS NULL;"
        ).fetchone()["properties"]
        degrees = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'symbol_degrees';"
        ).fetchone()
        conn.execute(
            "INSERT INTO graph_edges (source_symbol_id, edge_type, resolved) "
            "VALUES (1, 'IMPLEMENTS', 1);"
        )
        conn.commit()
    finally:
        conn.close()

    assert {"canonical_fqn", "visibility", "is_test", "is_entry_point", "importance"} <= (
        symbol_columns
    )
    assert {"properties"} <= edge_columns
    assert int(version) == SCHEMA_VERSION
    assert canonical["canonical_fqn"] == "src/Service.java::Service"
    assert canonical["is_test"] == 0
    assert canonical["is_entry_point"] == 0
    assert canonical["importance"] == 0
    assert properties == "{}"
    assert degrees is not None
