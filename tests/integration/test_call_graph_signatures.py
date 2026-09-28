"""Integration tests for call-graph signatures
reporting the truth.

Builds a controlled call graph with callees of varied signatures and asserts
each resolved callee's ``target_signature`` reflects the callee's own declared
signature — not the root's — while an overloaded callee reports the resolved
overload's signature with the overload set visible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.engine.config import Settings
from src.engine.graph import EdgeStore, GraphDatabase
from src.engine.symbols import SymbolStore


def _insert_symbol(
    conn: Any,
    fqn: str,
    name: str,
    kind: str,
    *,
    parent_symbol_id: int | None = None,
    file_path: str = "src/main.py",
) -> int:
    cursor = conn.execute(
        "INSERT INTO symbols (fqn, name, kind, file_path, line_start, line_end, "
        "column_start, column_end, language, parent_symbol_id) "
        "VALUES (?, ?, ?, ?, 1, 5, 0, 10, 'python', ?);",
        (fqn, name, kind, file_path, parent_symbol_id),
    )
    return cursor.lastrowid


def _call_edge(conn: Any, source_id: int, target_id: int) -> None:
    conn.execute(
        "INSERT INTO graph_edges (source_symbol_id, target_symbol_id, edge_type, "
        "source_range, target_range, resolved) "
        "VALUES (?, ?, 'CALLS', '[1,0,1,10]', NULL, 1);",
        (source_id, target_id),
    )


def _call_graph(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(context_dir=tmp_path)
    db = GraphDatabase(tmp_path / "signatures.db", settings)
    db.initialize()
    with db.write_transaction() as conn:
        root_id = _insert_symbol(
            conn, "com.example.Caller.run()", "run", "method", file_path="src/caller.py"
        )
        callee_a_id = _insert_symbol(
            conn,
            "com.example.CalleeA.transform(String)",
            "transform",
            "method",
            file_path="src/callee_a.py",
        )
        callee_b_id = _insert_symbol(
            conn,
            "com.example.CalleeB.process(String, int)",
            "process",
            "method",
            file_path="src/callee_b.py",
        )
        service_id = _insert_symbol(
            conn, "com.example.Service", "Service", "class", file_path="src/service.py"
        )
        save_one_id = _insert_symbol(
            conn,
            "com.example.Service.save(Article)",
            "save",
            "method",
            file_path="src/service.py",
            parent_symbol_id=service_id,
        )
        _insert_symbol(
            conn,
            "com.example.Service.save(Article, boolean)",
            "save",
            "method",
            file_path="src/service.py",
            parent_symbol_id=service_id,
        )
        _call_edge(conn, root_id, callee_a_id)
        _call_edge(conn, root_id, callee_b_id)
        _call_edge(conn, root_id, save_one_id)
        root_id_for_lookup = root_id
    return {
        "db": db,
        "root_id": root_id_for_lookup,
        "settings": settings,
    }


def test_callee_signatures_are_per_callee(tmp_path: Path) -> None:
    """Each resolved callee's ``target_signature`` matches
    its own declared signature, not the root's."""
    built = _call_graph(tmp_path)
    db: GraphDatabase = built["db"]
    symbol_store = SymbolStore(db, built["settings"])
    edge_store = EdgeStore(db)
    root = symbol_store.lookup_by_fqn("com.example.Caller.run()")
    assert root is not None
    graph = edge_store.get_call_graph(root["id"], direction="callees", max_depth=1)
    callees = graph["callees"]
    sig_by_name = {}
    for c in callees:
        assert c["resolved"] is True
        sig_by_name[c["fqn"].split(".")[-1].split("(")[0]] = c.get("target_signature")
    assert sig_by_name["transform"]["arity"] == 1, sig_by_name["transform"]
    assert sig_by_name["transform"]["param_types"] == ["String"]
    assert sig_by_name["process"]["arity"] == 2, sig_by_name["process"]
    assert sig_by_name["process"]["param_types"] == ["String", "int"]


def test_overloaded_callee_reports_resolved_overload_with_set_visible(
    tmp_path: Path,
) -> None:
    """An overloaded callee reports the resolved overload's signature
    while the overload set stays visible."""
    built = _call_graph(tmp_path)
    db: GraphDatabase = built["db"]
    symbol_store = SymbolStore(db, built["settings"])
    edge_store = EdgeStore(db)
    root = symbol_store.lookup_by_fqn("com.example.Caller.run()")
    assert root is not None
    graph = edge_store.get_call_graph(root["id"], direction="callees", max_depth=1)
    callees = graph["callees"]
    save_callee = next(c for c in callees if c["fqn"].endswith("save(Article)"))
    assert save_callee["resolved"] is True
    assert save_callee["target_signature"]["arity"] == 1, save_callee["target_signature"]
    assert save_callee["target_signature"]["param_types"] == ["Article"]
    overloads = save_callee.get("overloads") or []
    arities = sorted(o["arity"] for o in overloads)
    assert arities == [1, 2], f"the callee's own overload set must stay visible: {arities}"
