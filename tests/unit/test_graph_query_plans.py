"""Query-plan and index-hygiene checks for the graph access paths.

Every graph surface issues one of a small set of SQL shapes. These tests run
``EXPLAIN QUERY PLAN`` over each shape and fail when the planner stops using
the composite edge/containment indexes, which would turn a per-node lookup into
a table scan. They also assert that the redundant single-column edge indexes
are not recreated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_search.engine.config import Settings
from code_search.engine.cypher import DEAD_CODE_CYPHER, _register_functions, compile_cypher
from code_search.engine.graph import GraphDatabase


@pytest.fixture
def db(tmp_path: Path) -> GraphDatabase:
    """Return an initialized graph database with a few symbols and edges."""
    database = GraphDatabase(tmp_path / "graph.db", Settings(context_dir=tmp_path))
    database.initialize()
    with database.write_transaction() as conn:
        conn.executemany(
            "INSERT INTO symbols "
            "(id, fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, 'python');",
            [
                (1, "/repo/a.py::A", "A", "class", "/repo/a.py", 1, 5),
                (2, "/repo/a.py::A.run", "run", "method", "/repo/a.py", 2, 3),
                (3, "/repo/b.py::b", "b", "function", "/repo/b.py", 1, 2),
            ],
        )
        conn.executemany(
            "INSERT INTO graph_edges "
            "(source_symbol_id, target_symbol_id, edge_type, resolution_tier, resolved) "
            "VALUES (?, ?, 'CALLS', 'exact', 1);",
            [(3, 2), (2, 3)],
        )
        conn.execute("ANALYZE;")
    return database


def _plan(
    db: GraphDatabase, sql: str, params: dict[str, object] | list[object] | None = None
) -> str:
    """Return a compact EXPLAIN QUERY PLAN rendering."""
    with db.connect() as conn:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params or []).fetchall()
    return "\n".join(str(row["detail"]) for row in rows)


def test_redundant_edge_indexes_are_not_recreated(db: GraphDatabase) -> None:
    """The single-column edge indexes are dropped and stay dropped."""
    with db.connect() as conn:
        names = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index';")
        }
    assert "idx_edges_source" not in names
    assert "idx_edges_target" not in names
    assert "idx_edges_source_type" in names
    assert "idx_edges_target_type" in names


def test_outgoing_edge_lookup_uses_the_source_type_index(db: GraphDatabase) -> None:
    """One hop out is an index search, not an edge-table scan."""
    plan = _plan(
        db,
        "SELECT e.edge_type FROM graph_edges e "
        "WHERE e.source_symbol_id = ? AND e.edge_type IN ('CALLS');",
        [3],
    )
    assert "idx_edges_source_type" in plan
    assert "SCAN graph_edges" not in plan


def test_incoming_edge_lookup_uses_the_target_type_index(db: GraphDatabase) -> None:
    """One hop in is an index search, not an edge-table scan."""
    plan = _plan(
        db,
        "SELECT e.edge_type FROM graph_edges e "
        "WHERE e.target_symbol_id = ? AND e.edge_type IN ('CALLS');",
        [3],
    )
    assert "idx_edges_target_type" in plan
    assert "SCAN graph_edges" not in plan


def test_containment_lookup_uses_the_parent_index(db: GraphDatabase) -> None:
    """Member lookup is an index search on ``parent_symbol_id``."""
    plan = _plan(db, "SELECT id FROM symbols WHERE parent_symbol_id = ?;", [1])
    assert "idx_symbols_parent" in plan
    assert "SCAN symbols" not in plan


def test_cypher_dead_code_target_lookup_uses_an_index(db: GraphDatabase) -> None:
    """The correlated dead-code EXISTS searches the edge target index."""
    compiled = compile_cypher(DEAD_CODE_CYPHER)
    with db.connect() as conn:
        _register_functions(conn)
    plan = _plan(db, compiled.sql, compiled.params)
    assert "idx_edges_target_type" in plan
    # The EXISTS predicate must not degrade into a full scan of graph_edges.
    assert "SCAN graph_edges" not in plan


def test_cypher_variable_length_walk_uses_the_source_index(db: GraphDatabase) -> None:
    """The recursive step walks the source/type index."""
    compiled = compile_cypher("MATCH (a:Function)-[:CALLS*1..2]->(b:Function) RETURN count(*) AS n")
    with db.connect() as conn:
        _register_functions(conn)
    plan = _plan(db, compiled.sql, compiled.params)
    assert "idx_edges_source_type" in plan


def test_cypher_anchors_the_seed_on_start_properties(db: GraphDatabase) -> None:
    """A start-property filter is pushed into the recursive CTE seed."""
    compiled = compile_cypher(
        "MATCH (a:Function {name: 'b'})-[:CALLS*1..2]->(b) RETURN count(*) AS n"
    )
    assert "nodes.name = " in compiled.sql
