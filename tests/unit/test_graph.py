from pathlib import Path

import pytest

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.symbols import SymbolStore


@pytest.fixture
def db(tmp_path: Path) -> GraphDatabase:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "test.db", settings)
    db.initialize()
    return db


@pytest.fixture
def edge_store(db: GraphDatabase) -> EdgeStore:
    return EdgeStore(db)


@pytest.fixture
def populated_db(db: GraphDatabase) -> GraphDatabase:
    with db.write_transaction() as conn:
        for fqn, name, kind in [
            ("module.func_a", "func_a", "function"),
            ("module.func_b", "func_b", "function"),
            ("module.func_c", "func_c", "function"),
            ("module.ClassA", "ClassA", "class"),
        ]:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (fqn, name, kind, f"src/{name}.py", 1, 5, 0, 10, "python"),
            )
    return db


@pytest.fixture
def edge_store_with_data(populated_db: GraphDatabase) -> EdgeStore:
    es = EdgeStore(populated_db)
    with populated_db.connect() as conn:
        id_map: dict[str, int] = {}
        rows = conn.execute("SELECT id, fqn FROM symbols;").fetchall()
        for r in rows:
            id_map[r["fqn"]] = r["id"]

    edges = [
        {
            "source_symbol_id": id_map["module.func_a"],
            "target_symbol_id": id_map["module.func_b"],
            "edge_type": "CALLS",
            "source_range": "[1,0,1,10]",
            "target_range": None,
        },
        {
            "source_symbol_id": id_map["module.func_b"],
            "target_symbol_id": id_map["module.func_c"],
            "edge_type": "CALLS",
            "source_range": "[2,0,2,10]",
            "target_range": None,
        },
        {
            "source_symbol_id": id_map["module.func_a"],
            "target_symbol_id": id_map["module.ClassA"],
            "edge_type": "REFERENCES",
            "source_range": "[3,0,3,10]",
            "target_range": None,
        },
    ]
    es.insert_edges_batch(edges)
    return es


class TestGraphEdgeOperations:
    def test_insert_edge_success(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.b", "b", "function", "b.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            src_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.a';").fetchone()["id"]
            tgt_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.b';").fetchone()["id"]

        edge_id = edge_store.insert_edge(src_id, tgt_id, "CALLS", "[1,0,1,5]")
        assert edge_id is not None

        with db.connect() as conn:
            row = conn.execute("SELECT * FROM graph_edges WHERE id = ?;", (edge_id,)).fetchone()
        assert row is not None
        assert row["source_symbol_id"] == src_id
        assert row["target_symbol_id"] == tgt_id
        assert row["edge_type"] == "CALLS"

    def test_insert_edge_self_loop(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            sid = conn.execute("SELECT id FROM symbols WHERE fqn='src.a';").fetchone()["id"]

        result = edge_store.insert_edge(sid, sid, "CALLS")
        assert result is None

    def test_insert_edge_invalid_type(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.b", "b", "function", "b.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            src_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.a';").fetchone()["id"]
            tgt_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.b';").fetchone()["id"]

        result = edge_store.insert_edge(src_id, tgt_id, "INVALID_TYPE")
        assert result is None

    def test_insert_edges_batch(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.b", "b", "function", "b.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.c", "c", "function", "c.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            ids = {}
            for fqn in ("src.a", "src.b", "src.c"):
                row = conn.execute("SELECT id FROM symbols WHERE fqn=?;", (fqn,)).fetchone()
                if row:
                    ids[fqn] = row["id"]

        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["src.a"],
                    "target_symbol_id": ids["src.b"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["src.b"],
                    "target_symbol_id": ids["src.c"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
            ]
        )

        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM graph_edges;").fetchone()["cnt"]
        assert count == 2

    def test_duplicate_edge_prevention(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.b", "b", "function", "b.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            src_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.a';").fetchone()["id"]
            tgt_id = conn.execute("SELECT id FROM symbols WHERE fqn='src.b';").fetchone()["id"]

        edge_store.insert_edge(src_id, tgt_id, "CALLS")
        edge_store.insert_edge(src_id, tgt_id, "CALLS")

        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_edges "
                "WHERE source_symbol_id=? AND target_symbol_id=? AND edge_type='CALLS';",
                (src_id, tgt_id),
            ).fetchone()["cnt"]
        assert count == 1

    def test_edge_type_filtering(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.a", "a", "function", "a.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.b", "b", "function", "b.py", 1, 2, 0, 5, "python"),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.c", "c", "function", "c.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            ids = {}
            for fqn in ("src.a", "src.b", "src.c"):
                row = conn.execute("SELECT id FROM symbols WHERE fqn=?;", (fqn,)).fetchone()
                if row:
                    ids[fqn] = row["id"]

        edge_store.insert_edge(ids["src.a"], ids["src.b"], "CALLS")
        edge_store.insert_edge(ids["src.a"], ids["src.c"], "REFERENCES")
        edge_store.insert_edge(ids["src.a"], ids["src.c"], "IMPORTS")

        with db.connect() as conn:
            calls = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_edges WHERE edge_type='CALLS';"
            ).fetchone()["cnt"]
            refs = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_edges WHERE edge_type='REFERENCES';"
            ).fetchone()["cnt"]
            imports = conn.execute(
                "SELECT COUNT(*) as cnt FROM graph_edges WHERE edge_type='IMPORTS';"
            ).fetchone()["cnt"]
        assert calls == 1
        assert refs == 1
        assert imports == 1


class TestCycleDetection:
    def test_cycle_detection_callees(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        with db.write_transaction() as conn:
            for fqn, name in [("module.a", "a"), ("module.b", "b")]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "function", f"src/{name}.py", 1, 2, 0, 5, "python"),
                )
        with db.connect() as conn:
            id_a = conn.execute("SELECT id FROM symbols WHERE fqn='module.a';").fetchone()["id"]
            id_b = conn.execute("SELECT id FROM symbols WHERE fqn='module.b';").fetchone()["id"]

        edge_store.insert_edge(id_a, id_b, "CALLS")
        edge_store.insert_edge(id_b, id_a, "CALLS")

        graph = edge_store.get_call_graph(id_a, direction="callees", max_depth=10)
        callee_fqns = [c["fqn"] for c in graph["callees"]]
        assert "module.b" in callee_fqns
        assert all(c["depth"] <= 5 for c in graph["callees"])

    def test_cycle_detection_callers(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        with db.write_transaction() as conn:
            for fqn, name in [("module.a", "a"), ("module.b", "b")]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "function", f"src/{name}.py", 1, 2, 0, 5, "python"),
                )
        with db.connect() as conn:
            id_a = conn.execute("SELECT id FROM symbols WHERE fqn='module.a';").fetchone()["id"]
            id_b = conn.execute("SELECT id FROM symbols WHERE fqn='module.b';").fetchone()["id"]

        edge_store.insert_edge(id_b, id_a, "CALLS")
        edge_store.insert_edge(id_a, id_b, "CALLS")

        graph = edge_store.get_call_graph(id_a, direction="callers", max_depth=10)
        caller_fqns = [c["fqn"] for c in graph["callers"]]
        assert "module.b" in caller_fqns
        assert all(c["depth"] <= 5 for c in graph["callers"])

    def test_no_false_positive_cycle(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_a"),
            direction="callees",
            max_depth=3,
        )
        assert len(graph["callees"]) >= 1
        fqns = [c["fqn"] for c in graph["callees"]]
        assert "module.func_b" in fqns
        assert "module.func_c" in fqns


class TestCallGraphTraversal:
    def test_callers_traversal(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_b"),
            direction="callers",
        )
        assert len(graph["callers"]) >= 1
        assert graph["callees"] == []
        fqns = [c["fqn"] for c in graph["callers"]]
        assert "module.func_a" in fqns

    def test_callees_traversal(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_a"),
            direction="callees",
        )
        assert len(graph["callees"]) >= 1
        assert graph["callers"] == []
        fqns = [c["fqn"] for c in graph["callees"]]
        assert "module.func_b" in fqns

    def test_both_direction_traversal(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_b"),
            direction="both",
        )
        assert len(graph["callers"]) >= 1
        assert len(graph["callees"]) >= 1
        caller_fqns = [c["fqn"] for c in graph["callers"]]
        callee_fqns = [c["fqn"] for c in graph["callees"]]
        assert "module.func_a" in caller_fqns
        assert "module.func_c" in callee_fqns

    def test_recursive_cte_depth_limiting(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph_depth_1 = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_a"),
            direction="callees",
            max_depth=1,
        )
        graph_depth_3 = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_a"),
            direction="callees",
            max_depth=3,
        )
        depths_1 = {c["fqn"]: c["depth"] for c in graph_depth_1["callees"]}
        depths_3 = {c["fqn"]: c["depth"] for c in graph_depth_3["callees"]}
        assert "module.func_b" in depths_1
        assert depths_1["module.func_b"] == 1
        assert "module.func_c" in depths_3
        assert depths_3["module.func_c"] == 2

    def test_depth_clipped_to_max(
        self, edge_store_with_data: EdgeStore, populated_db: GraphDatabase
    ) -> None:
        graph = edge_store_with_data.get_call_graph(
            _get_sym_id(populated_db, "module.func_a"),
            direction="callees",
            max_depth=10,
        )
        for c in graph["callees"]:
            assert c["depth"] <= 5

    def test_self_loops_not_in_traversal(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.x", "x", "function", "x.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            sid = conn.execute("SELECT id FROM symbols WHERE fqn='src.x';").fetchone()["id"]

        edge_store.insert_edge(sid, sid, "CALLS")

        graph = edge_store.get_call_graph(sid, direction="both")
        assert len(graph["callers"]) == 0
        assert len(graph["callees"]) == 0

    def test_no_edges_returns_empty(self, edge_store: EdgeStore, db: GraphDatabase) -> None:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("src.orphan", "orphan", "function", "o.py", 1, 2, 0, 5, "python"),
            )
        with db.connect() as conn:
            sid = conn.execute("SELECT id FROM symbols WHERE fqn='src.orphan';").fetchone()["id"]

        graph = edge_store.get_call_graph(sid, direction="both")
        assert graph["callers"] == []
        assert graph["callees"] == []


class TestCallGraphDeduplication:
    """Deduplicated, minimum-depth neighbor traversal for callers and callees."""

    @staticmethod
    def _seed(db: GraphDatabase, specs: list[tuple[str, str]]) -> dict[str, int]:
        ids: dict[str, int] = {}
        with db.write_transaction() as conn:
            for fqn, name in specs:
                cur = conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, "function", f"src/{name}.py", 1, 5, 0, 10, "python"),
                )
                ids[fqn] = cur.lastrowid
        return ids

    def test_caller_direct_and_transitive_appears_once_at_depth_one(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.t", "t"), ("m.a", "a"), ("m.b", "b")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[3,0,3,5]",
                },
            ]
        )
        callers = edge_store.get_call_graph(ids["m.t"], direction="callers", max_depth=3)["callers"]
        assert [c["fqn"] for c in callers] == ["m.a", "m.b"]
        assert len([c for c in callers if c["fqn"] == "m.a"]) == 1
        assert next(c for c in callers if c["fqn"] == "m.a")["depth"] == 1

    def test_caller_shorter_depth_wins(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        ids = self._seed(db, [("m.t", "t"), ("m.a", "a"), ("m.b", "b"), ("m.c", "c")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": ids["m.c"],
                    "edge_type": "CALLS",
                    "source_range": "[3,0,3,5]",
                },
                {
                    "source_symbol_id": ids["m.c"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[4,0,4,5]",
                },
            ]
        )
        callers = edge_store.get_call_graph(ids["m.t"], direction="callers", max_depth=4)["callers"]
        depths = {c["fqn"]: c["depth"] for c in callers}
        assert depths == {"m.a": 1, "m.c": 1, "m.b": 2}
        assert [c["fqn"] for c in callers] == ["m.a", "m.c", "m.b"]

    def test_caller_cycle_terminates_each_neighbor_once(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.a", "a"), ("m.b", "b")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": ids["m.a"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
            ]
        )
        callers = edge_store.get_call_graph(ids["m.a"], direction="callers", max_depth=5)["callers"]
        assert sorted(c["fqn"] for c in callers) == ["m.a", "m.b"]
        assert len(callers) == 2

    def test_self_recursive_caller_appears_once_at_depth_one(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.x", "x")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.x"],
                    "target_symbol_id": ids["m.x"],
                    "edge_type": "CALLS",
                    "recursive": True,
                    "source_range": "[2,0,2,5]",
                },
            ]
        )
        callers = edge_store.get_call_graph(ids["m.x"], direction="callers", max_depth=5)["callers"]
        assert len(callers) == 1
        assert callers[0]["fqn"] == "m.x"
        assert callers[0]["depth"] == 1

    def test_caller_equal_depth_keeps_smallest_source_range(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.t", "t"), ("m.a", "a"), ("m.b", "b"), ("m.c", "c")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[9,0,9,5]",
                },
                {
                    "source_symbol_id": ids["m.a"],
                    "target_symbol_id": ids["m.c"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[3,0,3,5]",
                },
                {
                    "source_symbol_id": ids["m.c"],
                    "target_symbol_id": ids["m.t"],
                    "edge_type": "CALLS",
                    "source_range": "[4,0,4,5]",
                },
            ]
        )
        callers = edge_store.get_call_graph(ids["m.t"], direction="callers", max_depth=3)["callers"]
        a_rows = [c for c in callers if c["fqn"] == "m.a"]
        assert len(a_rows) == 1
        assert a_rows[0]["depth"] == 2
        assert a_rows[0]["source_range"] == "[2,0,2,5]"

    def test_callee_diamond_converges_to_one_entry_at_depth_two(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.t", "t"), ("m.b", "b"), ("m.c", "c"), ("m.d", "d")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.t"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.t"],
                    "target_symbol_id": ids["m.c"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": ids["m.d"],
                    "edge_type": "CALLS",
                    "source_range": "[3,0,3,5]",
                    "target_range": "[9,0,9,5]",
                },
                {
                    "source_symbol_id": ids["m.c"],
                    "target_symbol_id": ids["m.d"],
                    "edge_type": "CALLS",
                    "source_range": "[4,0,4,5]",
                    "target_range": "[2,0,2,5]",
                },
            ]
        )
        callees = edge_store.get_call_graph(ids["m.t"], direction="callees", max_depth=2)["callees"]
        d_rows = [c for c in callees if c["fqn"] == "m.d"]
        assert len(d_rows) == 1
        assert d_rows[0]["depth"] == 2
        assert d_rows[0]["target_range"] == "[2,0,2,5]"
        assert [c["fqn"] for c in callees] == ["m.b", "m.c", "m.d"]

    def test_callee_same_name_different_scope_stays_distinct(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(
            db, [("m.root", "root"), ("m.Alpha.save", "save"), ("m.Beta.save", "save")]
        )
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.Alpha.save"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.Beta.save"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
            ]
        )
        callees = edge_store.get_call_graph(ids["m.root"], direction="callees")["callees"]
        assert sorted(c["fqn"] for c in callees) == ["m.Alpha.save", "m.Beta.save"]

    def test_callee_distinct_overloads_stay_distinct(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.root", "root"), ("m.f(String)", "f"), ("m.f(int)", "f")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.f(String)"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.f(int)"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
            ]
        )
        callees = edge_store.get_call_graph(ids["m.root"], direction="callees")["callees"]
        assert sorted(c["fqn"] for c in callees) == ["m.f(String)", "m.f(int)"]

    def test_callee_unresolved_identity_collapses_only_identical_references(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db, [("m.root", "root"), ("m.b", "b"), ("m.c", "c")])
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.b"],
                    "edge_type": "CALLS",
                    "source_range": "[1,0,1,5]",
                },
                {
                    "source_symbol_id": ids["m.root"],
                    "target_symbol_id": ids["m.c"],
                    "edge_type": "CALLS",
                    "source_range": "[2,0,2,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": None,
                    "resolved": 0,
                    "target_raw": "ext.foo",
                    "edge_type": "CALLS",
                    "source_range": "[3,0,3,5]",
                },
                {
                    "source_symbol_id": ids["m.c"],
                    "target_symbol_id": None,
                    "resolved": 0,
                    "target_raw": "ext.foo",
                    "edge_type": "CALLS",
                    "source_range": "[4,0,4,5]",
                },
                {
                    "source_symbol_id": ids["m.b"],
                    "target_symbol_id": None,
                    "resolved": 0,
                    "target_raw": "ext.bar",
                    "edge_type": "CALLS",
                    "source_range": "[5,0,5,5]",
                },
            ]
        )
        callees = edge_store.get_call_graph(ids["m.root"], direction="callees", max_depth=2)[
            "callees"
        ]
        raw_fqns = sorted(c["fqn"] for c in callees if c.get("resolved") is False)
        assert raw_fqns == ["ext.bar", "ext.foo"]
        foo_rows = [c for c in callees if c["fqn"] == "ext.foo"]
        assert len(foo_rows) == 1
        assert foo_rows[0]["depth"] == 2
        assert foo_rows[0]["target_raw"] == "ext.foo"


class TestInheritanceTraversal:
    """Reverse (``get_subtypes``) and forward (``get_ancestors``) walks."""

    @staticmethod
    def _seed(db: GraphDatabase, specs: list[tuple[str, str, str]]) -> dict[str, int]:
        ids: dict[str, int] = {}
        with db.write_transaction() as conn:
            for fqn, name, kind in specs:
                cur = conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (fqn, name, kind, f"src/{name}.py", 1, 5, 0, 10, "python"),
                )
                ids[fqn] = cur.lastrowid
        return ids

    @staticmethod
    def _inherits(edge_store: EdgeStore, ids: dict[str, int], pairs: list[tuple[str, str]]) -> None:
        edge_store.insert_edges_batch(
            [
                {
                    "source_symbol_id": ids[src],
                    "target_symbol_id": ids[tgt],
                    "edge_type": "INHERITS",
                }
                for src, tgt in pairs
            ]
        )

    def test_subtypes_direct_and_indirect_depth(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(
            db,
            [
                ("m.I", "I", "interface"),
                ("m.Pet", "Pet", "interface"),
                ("m.Cat", "Cat", "class"),
            ],
        )
        self._inherits(edge_store, ids, [("m.Pet", "m.I"), ("m.Cat", "m.Pet")])
        subtypes = edge_store.get_subtypes(ids["m.I"])
        assert [(s["fqn"], s["depth"]) for s in subtypes] == [("m.Pet", 1), ("m.Cat", 2)]
        assert subtypes[1]["path"] == ["m.I", "m.Pet", "m.Cat"]

    def test_subtypes_min_depth_across_multiple_paths(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(
            db,
            [
                ("m.I", "I", "interface"),
                ("m.A", "A", "interface"),
                ("m.B", "B", "interface"),
                ("m.C", "C", "class"),
            ],
        )
        self._inherits(
            edge_store, ids, [("m.A", "m.I"), ("m.B", "m.A"), ("m.C", "m.I"), ("m.C", "m.B")]
        )
        subtypes = {s["fqn"]: s["depth"] for s in edge_store.get_subtypes(ids["m.I"])}
        assert subtypes == {"m.A": 1, "m.B": 2, "m.C": 1}
        assert [s["fqn"] for s in edge_store.get_subtypes(ids["m.I"])] == ["m.C", "m.A", "m.B"]

    def test_subtypes_cycle_terminates(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        ids = self._seed(
            db,
            [("m.I", "I", "interface"), ("m.A", "A", "class"), ("m.B", "B", "class")],
        )
        self._inherits(edge_store, ids, [("m.A", "m.I"), ("m.B", "m.A"), ("m.A", "m.B")])
        subtypes = edge_store.get_subtypes(ids["m.I"], max_depth=10)
        assert [s["fqn"] for s in subtypes] == ["m.A", "m.B"]

    def test_subtypes_depth_bounded(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        ids = self._seed(
            db,
            [
                ("m.I", "I", "interface"),
                ("m.A", "A", "interface"),
                ("m.B", "B", "class"),
            ],
        )
        self._inherits(edge_store, ids, [("m.A", "m.I"), ("m.B", "m.A")])
        assert [s["fqn"] for s in edge_store.get_subtypes(ids["m.I"], max_depth=1)] == ["m.A"]

    def test_ancestors_nearest_class_first(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        ids = self._seed(
            db,
            [
                ("m.I", "I", "interface"),
                ("m.Base", "Base", "class"),
                ("m.Mid", "Mid", "class"),
                ("m.Leaf", "Leaf", "class"),
            ],
        )
        self._inherits(
            edge_store,
            ids,
            [("m.Leaf", "m.Mid"), ("m.Leaf", "m.I"), ("m.Mid", "m.Base")],
        )
        ancestors = edge_store.get_ancestors(ids["m.Leaf"])
        assert [(a["fqn"], a["depth"]) for a in ancestors] == [("m.Mid", 1), ("m.Base", 2)]
        assert all(a["kind"] == "class" for a in ancestors)

    def test_ancestors_cycle_terminates(self, db: GraphDatabase, edge_store: EdgeStore) -> None:
        ids = self._seed(db, [("m.A", "A", "class"), ("m.B", "B", "class")])
        self._inherits(edge_store, ids, [("m.A", "m.B"), ("m.B", "m.A")])
        ancestors = edge_store.get_ancestors(ids["m.A"], max_depth=10)
        assert [a["fqn"] for a in ancestors] == ["m.B"]


def test_rebuild_fts_parity(db: GraphDatabase) -> None:
    with db.write_transaction() as conn:
        for i in range(4):
            conn.execute(
                "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
                "content, language) VALUES (?, ?, ?, ?, ?, ?);",
                (f"c{i}", f"file{i}.py", 1, 2, f"body {i}", "python"),
            )
    count = db.rebuild_fts()
    with db.connect() as conn:
        cc = conn.execute("SELECT COUNT(*) AS n FROM code_chunks;").fetchone()["n"]
        fc = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts;").fetchone()["n"]
    assert count == cc == fc
    assert db.fts_count() == cc


def test_fts_triggers_keep_index_in_sync(db: GraphDatabase) -> None:
    with db.write_transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("c1", "file1.py", 1, 2, "hello world", "python"),
        )
        chunk_id = cursor.lastrowid
    assert db.fts_count() == 1
    with db.write_transaction() as conn:
        conn.execute("DELETE FROM code_chunks WHERE id = ?;", (chunk_id,))
    assert db.fts_count() == 0


def test_fts_trigger_syncs_update(db: GraphDatabase) -> None:
    with db.write_transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO code_chunks (fqn, file_path, line_start, line_end, "
            "content, language) VALUES (?, ?, ?, ?, ?, ?);",
            ("c1", "file1.py", 1, 2, "old content", "python"),
        )
        chunk_id = cursor.lastrowid
        conn.execute("UPDATE code_chunks SET content = 'new content' WHERE id = ?;", (chunk_id,))
    assert db.fts_count() == 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT content FROM chunks_fts WHERE rowid = ?;", (chunk_id,)
        ).fetchone()
    assert row is not None and row["content"] == "new content"


def test_fts_metadata_store(db: GraphDatabase) -> None:
    from src.engine.graph import IndexMetadataStore

    meta = IndexMetadataStore(db)
    assert meta.get_fts_chunks() is None
    meta.set_fts_chunks(42)
    assert meta.get_fts_chunks() == 42


def test_cross_file_edge_batch_resolution(db: GraphDatabase) -> None:
    from src.engine.symbols import SymbolStore

    store = SymbolStore(db)
    syms_file_a = [
        {
            "fqn": "src/file_a.py::caller_func",
            "name": "caller_func",
            "kind": "function",
            "file_path": "src/file_a.py",
            "line_start": 1,
            "line_end": 5,
            "column_start": 0,
            "column_end": 10,
            "docstring": None,
            "language": "python",
            "parent_fqn": None,
        }
    ]
    id_map_a = store.insert_symbols_batch(syms_file_a)

    target_symbol_batch = [
        {
            "fqn": "src/file_b.py::target_func",
            "name": "target_func",
            "kind": "function",
            "file_path": "src/file_b.py",
            "line_start": 1,
            "line_end": 5,
            "column_start": 0,
            "column_end": 10,
            "docstring": None,
            "language": "python",
            "parent_fqn": None,
        }
    ]
    store.insert_symbols_batch(target_symbol_batch)

    unresolved = [
        {
            "source_fqn": "src/file_a.py::caller_func",
            "target_fqn": "src/file_b.py::target_func",
            "edge_type": "CALLS",
            "source_range": "[1,0,1,10]",
        }
    ]

    target_fqns = [e["target_fqn"] for e in unresolved]
    with db.connect() as conn:
        placeholders = ",".join("?" for _ in target_fqns)
        rows = conn.execute(
            f"SELECT fqn, id FROM symbols WHERE fqn IN ({placeholders});",
            target_fqns,
        ).fetchall()
    resolved_targets = {r["fqn"]: r["id"] for r in rows}

    from src.engine.graph import EdgeStore

    edge_store = EdgeStore(db)
    batch_edges = []
    for edge in unresolved:
        src_id = id_map_a.get(edge["source_fqn"])
        tgt_id = resolved_targets.get(edge["target_fqn"])
        if src_id is not None and tgt_id is not None:
            batch_edges.append(
                {
                    "source_symbol_id": src_id,
                    "target_symbol_id": tgt_id,
                    "edge_type": edge["edge_type"],
                    "source_range": edge.get("source_range"),
                }
            )
    if batch_edges:
        edge_store.insert_edges_batch(batch_edges)

    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM graph_edges WHERE edge_type='CALLS';"
        ).fetchone()["cnt"]
    assert count == 1, f"Expected 1 cross-file edge, got {count}"


def _get_sym_id(db: GraphDatabase, fqn: str) -> int:
    with db.connect() as conn:
        return conn.execute("SELECT id FROM symbols WHERE fqn=?;", (fqn,)).fetchone()["id"]


def test_get_symbol_definition_source_code_file_slice(
    db: GraphDatabase,
    edge_store: EdgeStore,
    tmp_path: Path,
) -> None:
    py_file = tmp_path / "svc.py"
    py_file.write_text("def outer():\n    def inner():\n        return 42\n    return inner()\n")
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("svc.outer.inner", "inner", "function", str(py_file), 1, 2, 8, 21, "python"),
        )

    result = edge_store.get_symbol_definition("svc.outer.inner")
    assert result is not None
    assert "def inner()" in result["source_code"]
    assert "return 42" in result["source_code"]


def test_get_symbol_definition_missing_file_source_code_empty(
    db: GraphDatabase,
    edge_store: EdgeStore,
) -> None:
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("svc.ghost", "ghost", "function", "src/ghost.py", 1, 5, 0, 10, "python"),
        )

    result = edge_store.get_symbol_definition("svc.ghost")
    assert result is not None
    assert result["source_code"] == ""


def test_get_symbol_definition_dotted_suffix_resolution(
    db: GraphDatabase,
    edge_store: EdgeStore,
) -> None:
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language, conventional_fqn) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/TokenService.java::TokenService.isTokenValid(String)",
                "isTokenValid",
                "method",
                "src/TokenService.java",
                3,
                7,
                4,
                40,
                "java",
                "com.example.TokenService.isTokenValid(String)",
            ),
        )

    result = edge_store.get_symbol_definition("TokenService.isTokenValid")
    assert result is not None
    assert result["name"] == "isTokenValid"
    assert result["fqn"] == "src/TokenService.java::TokenService.isTokenValid(String)"


def test_resolve_symbol_ambiguous_returns_candidates(
    db: GraphDatabase,
    edge_store: EdgeStore,
) -> None:
    with db.write_transaction() as conn:
        for fqn, name in [
            ("src/a.py::Logger", "Logger"),
            ("src/b.py::Logger", "Logger"),
        ]:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
            )

    symbol, candidates = edge_store.resolve_symbol_definition("Logger")
    assert symbol is None
    assert len(candidates) == 2
    assert {c["fqn"] for c in candidates} == {"src/a.py::Logger", "src/b.py::Logger"}


def test_get_symbol_definition_candidates_reported(
    db: GraphDatabase,
    edge_store: EdgeStore,
) -> None:
    with db.write_transaction() as conn:
        for fqn, name in [
            ("src/a.py::Logger", "Logger"),
            ("src/b.py::Logger", "Logger"),
        ]:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (fqn, name, "class", fqn.rsplit("::", 1)[0], 1, 5, 0, 10, "python"),
            )

    symbol, candidates = edge_store.resolve_symbol_definition("src/a.py::Logger")
    assert symbol is not None
    assert symbol["fqn"] == "src/a.py::Logger"
    assert candidates == []


def test_insert_edges_batch_rejects_spurious_self_edge(
    edge_store: EdgeStore, db: GraphDatabase
) -> None:
    """Batch inserts reject spurious source==target self-edges but keep
    genuine recursive self-calls (marked ``recursive=True``)."""
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/a.py::isAuthenticated",
                "isAuthenticated",
                "method",
                "a.py",
                1,
                5,
                0,
                10,
                "python",
            ),
        )
    with db.connect() as conn:
        sid = conn.execute(
            "SELECT id FROM symbols WHERE fqn='src/a.py::isAuthenticated';"
        ).fetchone()["id"]

    edge_store.insert_edges_batch(
        [
            {"source_symbol_id": sid, "target_symbol_id": sid, "edge_type": "CALLS"},
            {
                "source_symbol_id": sid,
                "target_symbol_id": sid,
                "edge_type": "CALLS",
                "recursive": True,
                "source_range": "[2,0,2,10]",
            },
        ]
    )
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM graph_edges WHERE source_symbol_id=?;", (sid,)
        ).fetchall()
    assert len(rows) == 1, f"Expected only the recursive self-edge, got {len(rows)}"
    assert rows[0]["source_symbol_id"] == rows[0]["target_symbol_id"]


def test_insert_edges_batch_uses_unique_constraint(
    edge_store: EdgeStore, db: GraphDatabase
) -> None:
    """The batch path still honours the (source, target, type) uniqueness."""
    with db.write_transaction() as conn:
        for fqn in ("src/a.py::x", "src/b.py::y"):
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    fqn,
                    fqn.rsplit("::", 1)[1],
                    "function",
                    fqn.split("::", 1)[0],
                    1,
                    5,
                    0,
                    10,
                    "python",
                ),
            )
    with db.connect() as conn:
        src = conn.execute("SELECT id FROM symbols WHERE fqn='src/a.py::x';").fetchone()["id"]
        tgt = conn.execute("SELECT id FROM symbols WHERE fqn='src/b.py::y';").fetchone()["id"]

    edge_store.insert_edges_batch(
        [
            {"source_symbol_id": src, "target_symbol_id": tgt, "edge_type": "CALLS"},
            {"source_symbol_id": src, "target_symbol_id": tgt, "edge_type": "CALLS"},
        ]
    )
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM graph_edges;").fetchone()["c"]
    assert count == 1


def test_edge_validation_sweep_removes_spurious_and_keeps_recursive(
    edge_store: EdgeStore, db: GraphDatabase
) -> None:
    """The sweep removes same-name-different-id mis-resolutions and
    out-of-range attachments while preserving genuine recursive self-calls."""
    with db.write_transaction() as conn:
        # genuine recursive self-call: walk -> walk, call line 3 inside decl 1..10
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("src/w.py::walk", "walk", "method", "src/w.py", 1, 10, 0, 40, "python"),
        )
        # same-name pair: save in a.py and save in b.py (same file name collides)
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("src/x.py::save", "save", "method", "src/x.py", 5, 9, 0, 40, "python"),
        )
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            ("src/x.py::save(String)", "save", "method", "src/x.py", 20, 25, 0, 40, "python"),
        )
    with db.connect() as conn:
        walk_id = conn.execute("SELECT id FROM symbols WHERE fqn='src/w.py::walk';").fetchone()[
            "id"
        ]
        save_a = conn.execute("SELECT id FROM symbols WHERE fqn='src/x.py::save';").fetchone()["id"]
        save_b = conn.execute(
            "SELECT id FROM symbols WHERE fqn='src/x.py::save(String)';"
        ).fetchone()["id"]

    edge_store.insert_edges_batch(
        [
            {
                "source_symbol_id": walk_id,
                "target_symbol_id": walk_id,
                "edge_type": "CALLS",
                "recursive": True,
                "source_range": "[3,0,3,20]",
            },
            {
                "source_symbol_id": save_a,
                "target_symbol_id": save_b,
                "edge_type": "CALLS",
                "source_range": "[6,0,6,20]",
                "resolution_tier": "same_file",
            },
        ]
    )
    summary = edge_store.run_edge_validation_sweep()
    assert summary["kept_recursive"] == 1
    assert summary["deleted"] == 1

    with db.connect() as conn:
        remaining = conn.execute(
            "SELECT source_symbol_id, target_symbol_id FROM graph_edges;"
        ).fetchall()
        pairs = [(row["source_symbol_id"], row["target_symbol_id"]) for row in remaining]
    assert pairs == [(walk_id, walk_id)]


def test_resolve_symbol_prefix_and_substring_stages(db: GraphDatabase) -> None:
    """Prefix/substring fallback stages resolve partial names."""
    from src.engine.graph import _resolve_symbol_candidates

    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/TokenService.java::TokenService.isTokenValid(String,String)",
                "isTokenValid",
                "method",
                "src/TokenService.java",
                3,
                7,
                4,
                40,
                "java",
            ),
        )

    with db.connect() as conn:
        prefix = _resolve_symbol_candidates(conn, "isToken")
    assert prefix, "prefix stage should return candidates"
    assert any(r["name"] == "isTokenValid" for r in prefix)


def test_resolve_symbol_edit_distance_suggestions(db: GraphDatabase) -> None:
    """Edit-distance <= 2 fallback returns 'did you mean' candidates."""
    from src.engine.graph import _resolve_symbol_candidates

    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
            "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (
                "src/TokenService.java::TokenService.isTokenValid(String,String)",
                "isTokenValid",
                "method",
                "src/TokenService.java",
                3,
                7,
                4,
                40,
                "java",
            ),
        )

    with db.connect() as conn:
        suggestions = _resolve_symbol_candidates(conn, "validateToken")
    assert suggestions, "edit-distance fallback should return suggestions"
    assert all(r.get("edit_distance") is not None for r in suggestions)
    assert any(r["name"] == "isTokenValid" for r in suggestions)


class TestResolveNameEnvelope:
    """SymbolStore.resolve_name classification and candidate shaping."""

    def test_kind_exact_unique_bare_name(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::UserService.isTokenValid",
                    "isTokenValid",
                    "method",
                    "service.py",
                    5,
                    8,
                    4,
                    30,
                    "python",
                ),
            )
        envelope = store.resolve_name("isTokenValid")
        assert envelope["kind"] == "exact"
        assert envelope["symbol"] is not None
        assert envelope["symbol"]["name"] == "isTokenValid"
        assert envelope["candidates"] == []

    def test_kind_exact_full_fqn(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::UserService.isTokenValid",
                    "isTokenValid",
                    "method",
                    "service.py",
                    5,
                    8,
                    4,
                    30,
                    "python",
                ),
            )
        envelope = store.resolve_name("service.py::UserService.isTokenValid")
        assert envelope["kind"] == "exact"
        assert envelope["candidates"] == []

    def test_kind_ambiguous_duplicates(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for i, file in enumerate(["a.py", "b.py"]):
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (f"{file}::Config", "Config", "class", file, i + 1, 5, 0, 10, "python"),
                )
        envelope = store.resolve_name("Config")
        assert envelope["kind"] == "ambiguous"
        assert envelope["symbol"] is None
        assert len(envelope["candidates"]) == 2
        assert {c["name"] for c in envelope["candidates"]} == {"Config"}

    def test_ambiguous_candidates_filtered_to_exact_name(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for i, file in enumerate(["a.py", "b.py"]):
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (f"{file}::Config", "Config", "class", file, i + 1, 5, 0, 10, "python"),
                )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("c.py::ConfigHelper", "ConfigHelper", "class", "c.py", 1, 5, 0, 10, "python"),
            )
        envelope = store.resolve_name("Config")
        assert envelope["kind"] == "ambiguous"
        assert all(c["name"] == "Config" for c in envelope["candidates"])
        assert len(envelope["candidates"]) == 2

    def test_deterministic_ordering_by_fqn_then_id(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for file in ["z_first.py", "a_second.py", "m_third.py"]:
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (f"{file}::Token", "Token", "class", file, 1, 5, 0, 10, "python"),
                )
        envelope = store.resolve_name("Token")
        fqns = [c["fqn"] for c in envelope["candidates"]]
        # The stable tie-break is ``fqn`` ascending (then ``id``), so identical
        # query + index state yields a deterministic order independent of the
        # storage insertion order.
        assert fqns == ["a_second.py::Token", "m_third.py::Token", "z_first.py::Token"]
        assert all("deterministic_tiebreak" in c["evidence"] for c in envelope["candidates"])

    def test_qualified_candidates_ordered_by_parent_scope(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for parent in ["Alpha", "Beta"]:
                parent_id = conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        f"src/{parent}.py::{parent}",
                        parent,
                        "class",
                        f"src/{parent}.py",
                        1,
                        20,
                        0,
                        5,
                        "python",
                    ),
                ).lastrowid
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language, parent_symbol_id) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        f"src/{parent}.py::{parent}.save",
                        "save",
                        "method",
                        f"src/{parent}.py",
                        2,
                        4,
                        4,
                        30,
                        "python",
                        parent_id,
                    ),
                )
        envelope = store.resolve_name("save")
        assert envelope["kind"] == "ambiguous"
        assert [c["parent_name"] for c in envelope["candidates"]] == ["Alpha", "Beta"]
        # A parent-qualified reference resolves to exactly one declaration.
        resolved = store.resolve_name("Beta.save")
        assert resolved["kind"] == "exact"
        assert resolved["symbol"]["parent_name"] == "Beta"

    def test_suffix_candidate_retrieval_and_ranking(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            parent_id = conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, conventional_fqn) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "src/Service.java::Service",
                    "Service",
                    "class",
                    "src/Service.java",
                    1,
                    20,
                    0,
                    5,
                    "java",
                    "com.example.Service",
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, conventional_fqn, parent_symbol_id) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "src/Service.java::Service.save(Article)",
                    "save",
                    "method",
                    "src/Service.java",
                    2,
                    4,
                    4,
                    30,
                    "java",
                    "com.example.Service.save(Article)",
                    parent_id,
                ),
            )
        envelope = store.resolve_name("example.Service.save")
        assert envelope["kind"] == "exact"
        assert envelope["symbol"]["name"] == "save"
        assert envelope["candidates"] == []

    def test_bounding_to_max_candidates(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            for i in range(12):
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        f"src/save_{i}.py::save",
                        "save",
                        "method",
                        f"src/save_{i}.py",
                        i,
                        5,
                        0,
                        10,
                        "python",
                    ),
                )
        envelope = store.resolve_name("save", max_candidates=3)
        assert envelope["kind"] == "ambiguous"
        assert len(envelope["candidates"]) == 3

    def test_bounding_honors_settings_default(self, db: GraphDatabase) -> None:
        from pathlib import Path

        settings = Settings(context_dir=Path(db._db_path).parent, max_resolution_candidates=3)
        store = SymbolStore(db, settings)
        with db.write_transaction() as conn:
            for i in range(12):
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        f"src/save_{i}.py::save",
                        "save",
                        "method",
                        f"src/save_{i}.py",
                        i,
                        5,
                        0,
                        10,
                        "python",
                    ),
                )
        envelope = store.resolve_name("save")
        assert envelope["kind"] == "ambiguous"
        assert len(envelope["candidates"]) == 3

    def test_parent_name_present_on_ambiguous_candidates(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            parent_a = conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::ArticleService",
                    "ArticleService",
                    "class",
                    "service.py",
                    1,
                    10,
                    0,
                    10,
                    "python",
                ),
            ).lastrowid
            parent_b = conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::CommentService",
                    "CommentService",
                    "class",
                    "service.py",
                    12,
                    20,
                    0,
                    10,
                    "python",
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, parent_symbol_id) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::ArticleService.save",
                    "save",
                    "method",
                    "service.py",
                    2,
                    4,
                    4,
                    30,
                    "python",
                    parent_a,
                ),
            )
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language, parent_symbol_id) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::CommentService.save",
                    "save",
                    "method",
                    "service.py",
                    13,
                    15,
                    4,
                    30,
                    "python",
                    parent_b,
                ),
            )
        envelope = store.resolve_name("save")
        assert envelope["kind"] == "ambiguous"
        parent_names = {c["parent_name"] for c in envelope["candidates"]}
        assert "parent_name" in envelope["candidates"][0]
        assert parent_names == {"ArticleService", "CommentService"}

    def test_kind_suggestion_near_miss(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "src/TokenService.java::TokenService.isTokenValid(String,String)",
                    "isTokenValid",
                    "method",
                    "src/TokenService.java",
                    3,
                    7,
                    4,
                    40,
                    "java",
                ),
            )
        envelope = store.resolve_name("validateToken")
        assert envelope["kind"] == "suggestion"
        assert envelope["symbol"] is None
        assert any(c["name"] == "isTokenValid" for c in envelope["candidates"])
        assert any(c.get("suggestion") for c in envelope["candidates"])
        for c in envelope["candidates"]:
            assert "edit_distance" in c
            assert c["edit_distance"] >= 0

    def test_kind_not_found(self, db: GraphDatabase) -> None:
        store = SymbolStore(db)
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                "column_start, column_end, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    "service.py::isTokenValid",
                    "isTokenValid",
                    "method",
                    "service.py",
                    5,
                    8,
                    4,
                    30,
                    "python",
                ),
            )
        envelope = store.resolve_name("definitelyNotReal123")
        assert envelope["kind"] == "not_found"
        assert envelope["symbol"] is None
        assert envelope["candidates"] == []


class TestEdgeSignature:
    def test_signature_from_fqn_generic_arity(self) -> None:
        from src.engine.graph import _signature_from_fqn

        sig = _signature_from_fqn("save(Article,Profile,List<Tag>)")
        assert sig is not None
        assert sig["arity"] == 3
        assert sig["param_types"] == ["Article", "Profile", "List"]

    def test_signature_from_fqn_generic_body_comma(self) -> None:
        from src.engine.graph import _signature_from_fqn

        sig = _signature_from_fqn("generateToken(Map<String,Object>,String)")
        assert sig is not None
        assert sig["arity"] == 2
        assert sig["param_types"] == ["Map", "String"]

    def test_signature_from_fqn_none_for_class(self) -> None:
        from src.engine.graph import _signature_from_fqn

        assert _signature_from_fqn("com.example.ArticleService") is None
        assert _signature_from_fqn(None) is None


class TestReceiverKeyedEdges:
    def _seed(self, db: GraphDatabase) -> dict[str, int]:
        """Service.save 3-arg (callee), a same-name repository.save (different
        receiver), and two real callers: the controller method and a test."""
        with db.write_transaction() as conn:
            for fqn, name, kind, parent in [
                ("com.example.ArticleService", "ArticleService", "class", None),
                ("com.example.ArticleRepository", "ArticleRepository", "class", None),
                (
                    "com.example.ArticleService.save(Article,Profile,List)",
                    "save",
                    "method",
                    "ArticleService",
                ),
                (
                    "com.example.ArticleRepository.save(Article)",
                    "save",
                    "method",
                    "ArticleRepository",
                ),
                (
                    "com.example.ArticleController.saveArticle(Article)",
                    "saveArticle",
                    "method",
                    "ArticleController",
                ),
                (
                    "com.example.ArticleController",
                    "ArticleController",
                    "class",
                    None,
                ),
            ]:
                parent_id = (
                    f"(SELECT id FROM symbols WHERE name = '{parent}')" if parent else "NULL"
                )
                conn.execute(
                    "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
                    "column_start, column_end, language, conventional_fqn, parent_symbol_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, " + parent_id + ");",
                    (
                        fqn,
                        name,
                        kind,
                        f"src/{name.split('.')[-1].split('(')[0]}.java",
                        1,
                        5,
                        0,
                        10,
                        "java",
                        fqn,
                    ),
                )
        id_map: dict[str, int] = {}
        with db.connect() as conn:
            for row in conn.execute("SELECT id, fqn FROM symbols;").fetchall():
                id_map[row["fqn"]] = row["id"]
        return id_map

    def test_edges_attached_to_correct_receiver(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db)
        svc_id = ids["com.example.ArticleService.save(Article,Profile,List)"]
        repo_save_id = ids["com.example.ArticleRepository.save(Article)"]
        ctl_save_id = ids["com.example.ArticleController.saveArticle(Article)"]
        es = EdgeStore(db)
        es.insert_edges_batch(
            [
                {
                    "source_symbol_id": ctl_save_id,
                    "target_symbol_id": svc_id,
                    "edge_type": "CALLS",
                    "source_range": "[10,4,10,30]",
                    "target_range": None,
                },
                {
                    "source_symbol_id": svc_id,
                    "target_symbol_id": repo_save_id,
                    "edge_type": "CALLS",
                    "source_range": "[20,4,20,30]",
                    "target_range": None,
                },
            ]
        )
        graph = es.get_call_graph(
            svc_id,
            direction="callers",
            max_depth=1,
        )
        callers = graph["callers"]
        assert len(callers) == 1, f"only the controller must be a caller: {callers}"
        assert "ArticleController" in callers[0]["fqn"]
        # repository.save is a callee of the service, never a caller.
        assert all("ArticleRepository.save" not in c["fqn"] for c in callers)

    def test_edges_carry_target_signature_and_overloads(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db)
        svc_id = ids["com.example.ArticleService.save(Article,Profile,List)"]
        ctl_save_id = ids["com.example.ArticleController.saveArticle(Article)"]
        es = EdgeStore(db)
        es.insert_edges_batch(
            [
                {
                    "source_symbol_id": ctl_save_id,
                    "target_symbol_id": svc_id,
                    "edge_type": "CALLS",
                    "source_range": "[10,4,10,30]",
                    "target_range": None,
                },
            ]
        )
        graph = es.get_call_graph(
            svc_id,
            direction="callers",
            max_depth=1,
        )
        caller = graph["callers"][0]
        assert caller["target_signature"]["arity"] == 3
        assert caller["overloads"] != []
        for ov in caller["overloads"]:
            assert "arity" in ov

    def test_unknown_receiver_same_name_produces_no_edge(
        self, db: GraphDatabase, edge_store: EdgeStore
    ) -> None:
        ids = self._seed(db)
        svc_id = ids["com.example.ArticleService.save(Article,Profile,List)"]
        repo_save_id = ids["com.example.ArticleRepository.save(Article)"]
        ctl_save_id = ids["com.example.ArticleController.saveArticle(Article)"]
        es = EdgeStore(db)
        # A bogus call from an unrelated method to the repository's save.
        es.insert_edges_batch(
            [
                {
                    "source_symbol_id": ctl_save_id,
                    "target_symbol_id": repo_save_id,
                    "edge_type": "CALLS",
                    "source_range": "[11,4,11,30]",
                    "target_range": None,
                },
            ]
        )
        graph = es.get_call_graph(
            svc_id,
            direction="callers",
            max_depth=1,
        )
        assert graph["callers"] == []
